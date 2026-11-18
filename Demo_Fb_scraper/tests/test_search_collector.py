"""Kiểm tra tìm kiếm, phân loại URL và chuyển kết quả sang crawler info-only."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fb_scraper.search import collector as search
from fb_scraper.search import reader as reader
from fb_scraper.storage import database as storage
from fb_scraper.storage import files as storage_files


class SearchParsingTests(unittest.TestCase):
    def test_search_urls_keep_keyword_and_correct_category(self):
        for kind, route in (("profile", "people"), ("group", "groups")):
            parsed = urlparse(reader.search_url("Nguyễn Văn A & B", kind))
            self.assertEqual(parsed.path, f"/search/{route}/")
            self.assertEqual(parse_qs(parsed.query)["q"], ["Nguyễn Văn A & B"])

    def test_filters_invalid_urls_and_duplicate_profile_links(self):
        links = [
            {"href": "https://m.facebook.com/zuck?ref=x", "name": "Mark Zuckerberg\ufeff"},
            {"href": "https://facebook.com/zuck/about", "name": "Mark Zuckerberg"},
            {"href": "https://facebook.com/zuck", "name": "Xem trang cá nhân"},
            {"href": "https://facebook.com/search/people?q=a", "name": "Mọi người"},
            {"href": "https://facebook.com/groups/123", "name": "Group"},
            {"href": "https://example.com/user", "name": "User"},
            {"href": "https://facebook.com/profile.php?id=456", "name": "  Nguyễn   Văn A "},
        ]
        self.assertEqual(reader.normalize_results(links, "profile"), [
            {"url": "https://www.facebook.com/zuck", "name": "Mark Zuckerberg"},
            {"url": "https://www.facebook.com/profile.php?id=456", "name": "Nguyễn Văn A"},
        ])

    def test_group_titles_exclude_profile_and_post_links(self):
        links = [{"href": "https://facebook.com/groups/pythonvietnam/about/", "name": "Python Vietnam"},
                 {"href": "https://facebook.com/groups/123/posts/456", "name": "Post"},
                 {"href": "https://facebook.com/groups/feed", "name": "Groups"},
                 {"href": "https://facebook.com/zuck", "name": "Mark"}]
        self.assertEqual(reader.normalize_results(links, "group"),
                         [{"url": "https://www.facebook.com/groups/pythonvietnam", "name": "Python Vietnam"}])

    def test_validates_limits_and_deduplicates_keywords(self):
        args = search.argument_parser().parse_args(["  Python   Việt Nam ", "python Việt nam", "Messi"])
        self.assertEqual(search.validate_args(args), ["Python Việt Nam", "Messi"])
        for flags in (["   "], ["Python", "--max-results", "-1"], ["Python", "--max-scrolls", "-1"]):
            with self.assertRaises(ValueError):
                search.validate_args(search.argument_parser().parse_args(flags))


class SearchIterationTests(unittest.IsolatedAsyncioTestCase):
    def link(self, number):
        return {"href": f"https://www.facebook.com/profile.php?id={number}", "name": f"User {number}"}

    def page(self, snapshots, url=None):
        iterator = iter(snapshots)

        async def evaluate(script):
            if script == reader.EXTRACT_RESULTS_JS:
                return next(iterator)

        return SimpleNamespace(
            url=url or reader.search_url("Test", "profile"),
            goto=AsyncMock(return_value=SimpleNamespace(status=200)),
            locator=lambda selector: SimpleNamespace(first=SimpleNamespace(wait_for=AsyncMock())),
            evaluate=AsyncMock(side_effect=evaluate),
            wait_for_function=AsyncMock(),
        )

    async def collect(self, page, **kwargs):
        with patch.object(reader.asyncio, "sleep", new=AsyncMock()):
            return [result async for result in reader.iter_keyword_results(page, "Test", "profile", **kwargs)]

    async def test_scrolls_deduplicates_and_respects_maximum(self):
        page = self.page([{"links": [self.link(1), self.link(1), self.link(2)], "end": False},
                          {"links": [self.link(2), self.link(3), self.link(4)], "end": False}])
        results = await self.collect(page, max_results=3)
        self.assertEqual([item["name"] for item in results], ["User 1", "User 2", "User 3"])
        self.assertTrue(all(item["keyword"] == "Test" and item["entity_type"] == "profile" for item in results))
        self.assertEqual(sum(call.args[0] == reader.SCROLL_RESULTS_JS for call in page.evaluate.await_args_list), 1)

    async def test_unlimited_results_stop_at_scroll_limit(self):
        page = self.page([{"links": [self.link(1)], "end": False}, {"links": [self.link(2)], "end": False}])
        results = await self.collect(page, max_results=0, max_scrolls=1)
        self.assertEqual(len(results), 2)

    async def test_stops_when_no_new_results_load(self):
        page = self.page([{"links": [self.link(1)], "end": False}] * 5)
        results = await self.collect(page, max_results=0, max_idle=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(sum(call.args[0] == reader.EXTRACT_RESULTS_JS for call in page.evaluate.await_args_list), 4)

    async def test_empty_search_stops_without_scrolling(self):
        page = self.page([{"links": [], "end": True}])
        self.assertEqual(await self.collect(page), [])
        self.assertEqual(page.evaluate.await_count, 1)

    async def test_login_and_wrong_redirect_never_read_result_links(self):
        for url in ("https://www.facebook.com/login/", "https://www.facebook.com/search/people/", "https://www.facebook.com/zuck"):
            page = self.page([], url=url)
            with self.assertRaises(RuntimeError):
                await self.collect(page)
            page.evaluate.assert_not_awaited()


class SearchDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "data"
        for name, value in {"DATA": self.data, "IMG_DIR": self.data / "images",
                            "DB_PATH": self.data / "posts.db", "JSONL_PATH": self.data / "posts.jsonl"}.items():
            self.enterContext(patch.object(storage, name, value))

    async def run_search(self, flags, behavior, locked_manifest=False):
        page = SimpleNamespace(close=AsyncMock(), url="https://www.facebook.com/search/people/?q=Test")
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context

        async def results(page, keyword, kind, max_results, max_scrolls):
            for number in behavior(keyword, kind):
                url = f"https://www.facebook.com/profile.php?id={number}" if kind == "profile" else f"https://www.facebook.com/groups/{number}"
                yield {"keyword": keyword, "entity_type": kind, "url": url, "name": str(number),
                       "search_url": reader.search_url(keyword, kind), "found_at": "2026-10-08T00:00:00+00:00"}

        original = Path.replace
        callbacks = {"profile": AsyncMock(), "group": AsyncMock()}
        connections = []

        async def dispatch(ctx, urls, kind, options, *, db):
            self.assertIs(ctx, context)
            connections.append(db)
            await callbacks[kind](urls, options)

        def replace_file(path, target):
            if locked_manifest and target.name == "sources.jsonl":
                raise PermissionError("file locked")
            return original(path, target)

        with patch.object(search, "browser_context", return_value=manager) as connect, \
             patch.object(search, "iter_keyword_results", new=results), \
             patch.object(search, "collect_entities", new=dispatch), \
             patch.object(Path, "replace", autospec=True, side_effect=replace_file), \
             patch.object(storage_files.time, "sleep"):
            await search.main(search.argument_parser().parse_args(flags))
        connect.assert_called_once()
        if connections:
            self.assertTrue(all(db is connections[0] for db in connections))
        profile, group = callbacks["profile"], callbacks["group"]
        page.close.assert_awaited_once()
        return profile, group

    async def test_both_modes_dispatch_all_results_as_info_only(self):
        profile, group = await self.run_search(["Test"], lambda keyword, kind: [1, 2, 3])
        for callback in (profile, group):
            callback.assert_awaited_once()
            urls, args = callback.await_args.args
            self.assertEqual(len(urls), 3)
            self.assertTrue(args.info_only)
            self.assertEqual(args.max_posts, 0)
            self.assertEqual(args.max_comments, 0)
            self.assertFalse(args.ocr)
        records = [result for line in (self.data / "sources.jsonl").read_text(encoding="utf-8").splitlines()
                   for result in json.loads(line)["metadata"].get("search_history", [])]
        self.assertEqual(len(records), 6)
        self.assertEqual({item["entity_type"] for item in records}, {"profile", "group"})

    async def test_same_url_from_multiple_keywords_is_collected_once(self):
        profile, group = await self.run_search(["Test", "Other", "--type", "profile"], lambda keyword, kind: [1, 2])
        self.assertEqual(len(profile.await_args.args[0]), 2)
        group.assert_not_awaited()
        records = [result for line in (self.data / "sources.jsonl").read_text(encoding="utf-8").splitlines()
                   for result in json.loads(line)["metadata"].get("search_history", [])]
        self.assertEqual(len(records), 4)

    async def test_group_only_and_empty_results_do_not_run_profile_collector(self):
        profile, group = await self.run_search(["Test", "--type", "group"], lambda keyword, kind: [])
        profile.assert_not_awaited()
        group.assert_not_awaited()

    async def test_locked_manifest_does_not_prevent_info_collection(self):
        profile, group = await self.run_search(["Test", "--type", "profile"], lambda keyword, kind: [1, 2], locked_manifest=True)
        self.assertEqual(len(profile.await_args.args[0]), 2)
        group.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
