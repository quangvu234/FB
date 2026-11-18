"""Kiểm tra URL, trích xuất thông tin, nâng cấp SQLite và điều phối nguồn mới."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fb_scraper.posts import pipeline as collector
from fb_scraper.posts import parser as parser
from fb_scraper.posts import reader as reader
from fb_scraper.entities import collector as entities
from fb_scraper.common.models import CollectionOptions
from fb_scraper.storage import database as storage
from fb_scraper.entities.parser import parse_entity
from fb_scraper.common.numbers import parse_count
from fb_scraper.storage import files as storage_files
from fb_scraper.common.urls import canonical_entity_url, entity_about_url

PROFILE = "https://www.facebook.com/zuck"
GROUP = "https://www.facebook.com/groups/pythonvietnam"


class EntityParsingTests(unittest.TestCase):
    def test_normalizes_profile_group_and_about_urls(self):
        self.assertEqual(canonical_entity_url("https://m.facebook.com/zuck/about?ref=x", "profile"), PROFILE)
        self.assertEqual(canonical_entity_url(GROUP + "/about/", "group"), GROUP)
        self.assertEqual(entity_about_url("https://facebook.com/profile.php?id=123&ref=x", "profile"),
                         "https://www.facebook.com/profile.php?id=123&sk=about")
        self.assertEqual(entity_about_url("https://facebook.com/pages/demo/123", "profile"),
                         "https://www.facebook.com/pages/demo/123/about")
        self.assertEqual(canonical_entity_url("https://facebook.com/people/Nguyen-Van-A/123/about", "profile"),
                         "https://www.facebook.com/people/Nguyen-Van-A/123")
        for url, kind in (("https://facebook.com/search/posts?q=a", "profile"),
                          (GROUP + "/posts/123", "group"), ("https://facebook.com/groups/feed", "group"),
                          ("https://example.com/zuck", "profile"), (PROFILE + "/posts/123", "profile")):
            self.assertEqual(canonical_entity_url(url, kind), "")

    def test_counts_in_vietnamese_and_english(self):
        for raw, value in (("121 triệu", 121000000), ("56,1K", 56100), ("56.060", 56060),
                           ("56,060", 56060), ("1.2 million", 1200000), ("2 nghìn", 2000), ("3 Tr", 3000000)):
            self.assertEqual(parse_count(raw), value)
        self.assertIsNone(parse_count("không biết"))

    def test_profile_without_h1_and_separate_bio(self):
        root = {"text": "Mark Zuckerberg\n121 triệu người theo dõi\nTheo dõi\nThông tin cá nhân\nSống ở Palo Alto, California\nTừ Dobbs Ferry\n14 tháng 5, 1984\nCông việc\nMeta\nFounder and CEO\nXem thêm công việc\nGiáo dục\nHarvard University\nXem thêm học vấn\nBài viết\nCông việc\nNội dung bài viết không được lấy", "headings": ["Thông tin cá nhân", "Công việc", "Giáo dục", "Bài viết"]}
        about = {"text": "Mark Zuckerberg\nTiểu sử\nBringing the world closer together.\nReels\n12345", "about_page": True}
        row = parse_entity(PROFILE, "profile", [root, about])
        self.assertEqual(row["name"], "Mark Zuckerberg")
        self.assertEqual(row["followers_count"], 121000000)
        self.assertEqual(row["work"], ["Meta", "Founder and CEO"])
        self.assertEqual(row["education"], ["Harvard University"])
        self.assertEqual(row["current_city"], "Palo Alto, California")
        self.assertEqual(row["bio"], "Bringing the world closer together.")
        self.assertIsNone(row["profile_id"])
        self.assertNotIn("1984", json.dumps(row))
        self.assertNotIn("Nội dung bài viết", json.dumps(row))

    def test_group_prefers_exact_members_and_stops_description(self):
        row = parse_entity(GROUP, "group", [
            {"name": "Python Vietnam", "text": "Python Vietnam\nNhóm Công khai\n56,1K thành viên"},
            {"name": "Python Vietnam", "text": "Python Vietnam\nGiới thiệu về nhóm này\ntham gia nếu bạn đam mê Python\nCông khai\nBất kỳ ai cũng có thể nhìn thấy mọi người\nThành viên\nQuản trị viên A\nHoạt động\nTổng cộng 56.060 thành viên"},
        ])
        self.assertEqual(row["members_count"], 56060)
        self.assertEqual(row["members_raw"], "Tổng cộng 56.060 thành viên")
        self.assertEqual(row["description"], "tham gia nếu bạn đam mê Python")
        self.assertEqual(row["privacy"], "public")
        self.assertIsNone(row["rules"])
        self.assertIsNone(row["group_id"])
        self.assertNotIn("Quản trị viên A", json.dumps(row))

    def test_education_panel_with_college_and_high_school(self):
        row = parse_entity(PROFILE, "profile", [{"about_page": True,
            "text": "Mark Zuckerberg\nTrình độ học vấn\nThông tin pháp lý và quyền riêng tư\nĐại học\nHọc tại Harvard\nChuyên ngành: Computer Science\nTrường trung học\nPhillips Exeter\nTốt nghiệp năm 2002\nReels\n4 triệu"}])
        self.assertEqual(row["education"], ["Học tại Harvard", "Chuyên ngành: Computer Science", "Phillips Exeter", "Tốt nghiệp năm 2002"])

    def test_private_group_rules_and_numeric_id(self):
        row = parse_entity("https://facebook.com/groups/123", "group", [{"name": "Demo", "text": "Demo\nPrivate group\n100 members\nAbout this group\nDescription\nPrivate\nGroup rules\n1. Be kind\n2. No spam\nActivity\n99 posts"}])
        self.assertEqual(row["group_id"], "123")
        self.assertEqual(row["privacy"], "private")
        self.assertEqual(row["rules"], ["1. Be kind", "2. No spam"])

    def test_unavailable_and_missing_fields(self):
        row = parse_entity(PROFILE, "profile", [{"unavailable": True, "text": "Bạn hiện không xem được nội dung này"}])
        self.assertIsNone(row["name"])
        self.assertEqual(row["collection_status"], "unavailable")
        row = parse_entity(PROFILE, "profile", [{"login_required": True}])
        self.assertEqual(row["collection_status"], "login_required")
        row = parse_entity(PROFILE, "profile", [{"text": "Mark Zuckerberg"}])
        self.assertIsNone(row["education"])
        self.assertIsNone(row["current_city"])

    def test_unified_command_validates_sources_and_limits(self):
        args = entities.argument_parser().parse_args([PROFILE, PROFILE + "/about", "--type", "profile", "--info-only"])
        self.assertEqual(entities.validate_sources(args.urls, args.type), [PROFILE])
        self.assertEqual(entities.validate_sources([GROUP], "group"), [GROUP])
        with self.assertRaises(ValueError):
            entities.validate_sources([GROUP], "profile")
        with self.assertRaises(ValueError):
            CollectionOptions(max_comments=-1)

    def test_comment_permalink_does_not_supply_post_time(self):
        raw = {"text": "Nội dung bài viết công khai của tác giả.", "author": "Mark", "imgs": [],
               "links": [{"href": PROFILE + "/posts/123?comment_id=456", "text": "1 tuần"}]}
        post = parser.parse_article(raw, "profile:u_zuck")
        self.assertEqual(post["url"], PROFILE + "/posts/123")
        self.assertEqual(post["posted_raw"], "")
        self.assertIsNone(post["posted_at"])
        raw["links"].append({"href": PROFILE + "/posts/123", "text": "2 giờ"})
        self.assertEqual(parser.parse_article(raw, "profile:u_zuck")["posted_raw"], "2 giờ")


class EntityStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "data"
        for name, value in {"DATA": self.data, "IMG_DIR": self.data / "images", "DB_PATH": self.data / "posts.db",
                            "JSONL_PATH": self.data / "posts.jsonl"}.items():
            override = patch.object(storage, name, value)
            override.start()
            self.addCleanup(override.stop)

    def test_migrates_existing_posts_and_preserves_comments(self):
        self.data.mkdir()
        db = sqlite3.connect(storage.DB_PATH)
        db.execute("CREATE TABLE posts(post_id TEXT PRIMARY KEY, url TEXT, source TEXT, author TEXT, text TEXT, posted_raw TEXT, posted_at TEXT, likes INT, comments INT, shares INT, links TEXT, images TEXT, image_files TEXT, ocr TEXT, top_comments TEXT, collected_at TEXT)")
        db.execute("INSERT INTO posts(post_id, top_comments) VALUES (?, ?)", ("123", '["existing comment"]'))
        db.commit()
        db.close()
        db = storage.init_db()
        self.addCleanup(db.close)
        self.assertEqual(storage.load_post(db, "123")["top_comments"][0]["text"], "existing comment")
        self.assertIsNone(storage.load_post(db, "123")["entity_type"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='profiles'").fetchone())

    def test_upserts_entities_lists_and_keeps_last_metadata_on_failure(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        row = parse_entity(PROFILE, "profile", [{"text": "Mark Zuckerberg\nCông việc\nMeta\nGiáo dục\nHarvard"}])
        storage.save_entity(db, "profile", row)
        failed = parse_entity(PROFILE, "profile", [{"login_required": True}])
        storage.save_entity(db, "profile", failed)
        storage.export_entities(db, "profile")
        rows = [json.loads(line)["metadata"]["entity"] for line in (self.data / "sources.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["work"], ["Meta"])
        self.assertEqual(rows[0]["collection_status"], "login_required")
        self.assertIsNone(rows[0]["current_city"])
        self.assertIsNotNone(rows[0]["collected_at"])

    def test_entity_lock_keeps_database_and_pending_snapshot(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        original = Path.replace
        target = self.data / "sources.jsonl"

        def locked(source, destination):
            if destination == target:
                raise PermissionError("locked")
            return original(source, destination)

        with patch.object(Path, "replace", autospec=True, side_effect=locked), patch.object(storage_files.time, "sleep"):
            storage.save_entity(db, "group", parse_entity(GROUP, "group", [{"name": "Python Vietnam"}]))
            self.assertFalse(storage.export_entities(db, "group"))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sources WHERE source_type='group'").fetchone()[0], 1)
        self.assertTrue((self.data / "sources.pending.jsonl").is_file())
        self.assertTrue(storage.export_entities(db, "group"))
        self.assertFalse((self.data / "sources.pending.jsonl").exists())

    def test_post_association_survives_keyword_update(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        post = {"post_id": "123", "text": "Post", "entity_type": "group", "entity_id": "u_pythonvietnam"}
        storage.save_post(db, post)
        storage.save_post(db, {"post_id": "123", "text": "Updated", "top_comments": ["Comment"]})
        row = storage.load_post(db, "123")
        self.assertEqual(row["entity_id"], "u_pythonvietnam")
        self.assertEqual(row["top_comments"][0]["text"], "Comment")

    async def run_collector(self, kind, flags, entity, posts=()):
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context
        requests = []

        async def source(page, src, count):
            requests.append(src)
            for post in posts:
                yield dict(post)

        with patch.object(entities, "browser_context", return_value=manager), \
             patch.object(entities, "scrape_entity", new=AsyncMock(return_value=entity)) as scrape, \
             patch.object(collector, "iter_source_posts", new=source), \
             patch.object(collector, "scrape_top_comments", new=AsyncMock(return_value=[])), \
             patch.object(collector, "download_images", new=AsyncMock(return_value=[])):
            await entities.main(entities.argument_parser().parse_args(flags + ["--type", kind]))
        page.close.assert_awaited_once()
        self.assertEqual(scrape.await_count, 1)
        return requests

    async def test_info_only_saves_profile_without_posts(self):
        entity = parse_entity(PROFILE, "profile", [{"name": "Mark Zuckerberg"}])
        requests = await self.run_collector("profile", [PROFILE, "--info-only"], entity)
        self.assertEqual(requests, [])
        self.assertEqual(json.loads((self.data / "sources.jsonl").read_text(encoding="utf-8"))["source_label"], "Mark Zuckerberg")
        self.assertEqual((self.data / "posts.jsonl").read_text(encoding="utf-8"), "")

    async def test_explicit_page_type_is_stored_as_page_source(self):
        entity = parse_entity(PROFILE, "profile", [{"name": "Example Page"}])
        await self.run_collector("page", [PROFILE, "--info-only"], entity)
        source = json.loads((self.data / "sources.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(source["source_type"], "page")

    async def test_private_and_unknown_group_never_collect_posts(self):
        for privacy in ("private", None):
            entity = parse_entity(GROUP, "group", [{"name": "Demo"}])
            entity["privacy"] = privacy
            requests = await self.run_collector("group", [GROUP, "--max-posts", "1"], entity)
            self.assertEqual(requests, [])

    async def test_public_group_posts_have_entity_association(self):
        entity = parse_entity(GROUP, "group", [{"name": "Python Vietnam", "text": "Python Vietnam\nNhóm Công khai"}])
        requests = await self.run_collector("group", [GROUP, "--max-posts", "1"], entity,
                                             [{"post_id": "123", "url": GROUP + "/posts/123", "text": "Public post", "images": []}])
        self.assertEqual(requests[0]["name"], "group:u_pythonvietnam")
        db = sqlite3.connect(storage.DB_PATH)
        self.addCleanup(db.close)
        row = storage.load_post(db, "123")
        self.assertEqual(row["entity_type"], "group")
        self.assertEqual(row["entity_id"], "u_pythonvietnam")

    async def test_profile_feed_skips_posts_without_public_marker(self):
        posts = [{"text": "Nội dung bài viết dùng để kiểm tra công khai.", "author": "Author", "imgs": [],
                  "links": [{"href": PROFILE + f"/posts/{number}", "text": "2 giờ"}], "public_post": public}
                 for number, public in ((1, False), (2, True))]
        page = SimpleNamespace(goto=AsyncMock(), url=PROFILE, title=AsyncMock(return_value="Profile"),
                               evaluate=AsyncMock(return_value=posts), mouse=SimpleNamespace(wheel=AsyncMock()))
        src = {"name": "profile:u_zuck", "url": PROFILE, "public_only": True}
        with patch.object(reader, "human_pause", new=AsyncMock()), patch.object(reader, "expand_see_more", new=AsyncMock()):
            result = [post async for post in reader.iter_source_posts(page, src, max_posts=1)]
        self.assertEqual([post["post_id"] for post in result], ["2"])


if __name__ == "__main__":
    unittest.main()
