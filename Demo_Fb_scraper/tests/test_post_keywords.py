"""Kiểm tra từ khóa tiếng Việt được truyền đúng vào nguồn tìm bài."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fb_scraper.posts import collector
from tests.persistence_fixtures import PersistenceFixture


class PostKeywordTests(PersistenceFixture, unittest.IsolatedAsyncioTestCase):
    async def test_cli_keywords_reach_collector_without_default_source(self):
        keywords = ["việc làm online tại nhà", "C++ & việc làm #1? lương=10%"]
        flags = ["--max-posts", "2"]
        for keyword in keywords:
            flags.extend(["--keyword", keyword])
        args = collector.argument_parser().parse_args(flags)
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context

        with patch.object(collector, "browser_context", return_value=manager), \
             patch.object(collector, "collect_source_posts", new=AsyncMock()) as collect:
            await collector.main(args)

        self.assertEqual(collect.await_count, len(keywords))
        for call, keyword in zip(collect.await_args_list, keywords):
            source = call.args[3]
            url = urlparse(source["url"])
            self.assertEqual(source["name"], f"kw:{keyword}")
            self.assertEqual(url.path, "/search/posts")
            self.assertEqual(parse_qs(url.query), {"q": [keyword]})
            self.assertEqual(url.fragment, "")
            self.assertTrue(source["url"].isascii())
            self.assertEqual(call.args[4].max_posts, 2)
        page.close.assert_awaited_once()

    async def test_default_keywords_are_encoded_automatically(self):
        args = collector.argument_parser().parse_args([])
        with patch.object(collector, "KEYWORDS", ["việc làm tại nhà"]):
            source, = collector.build_sources(args.keywords)
        self.assertEqual(parse_qs(urlparse(source["url"]).query), {"q": ["việc làm tại nhà"]})

    async def test_blank_keyword_fails_before_browser_or_database(self):
        args = collector.argument_parser().parse_args(["--keyword", "  "])
        with patch.object(collector, "browser_context") as browser, \
             patch.object(collector, "init_db") as database:
            with self.assertRaisesRegex(ValueError, "Từ khóa không được rỗng"):
                await collector.main(args)
        browser.assert_not_called()
        database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
