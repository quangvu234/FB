"""Kiểm tra lưu bài trước khi bổ sung bình luận/ảnh/OCR và xử lý ngắt."""
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fb_scraper.posts import collector as collector
from fb_scraper.posts import pipeline as pipeline
from fb_scraper.posts import reader as reader
from fb_scraper.storage import database as storage
from fb_scraper.storage import files as storage_files
from tests.persistence_fixtures import PersistenceFixture


class PostPipelineTests(PersistenceFixture, unittest.IsolatedAsyncioTestCase):
    async def test_collector_saves_before_enrichment_and_survives_interruption(self):
        raw = {
            "text": self.post().text, "author": "Tác giả", "imgs": [],
            "links": [{"href": self.post().url, "text": "2 giờ"}],
        }
        page = SimpleNamespace(
            url="https://www.facebook.com/example", goto=AsyncMock(return_value=None),
            title=AsyncMock(return_value="Fixture"), evaluate=AsyncMock(return_value=[raw]),
            close=AsyncMock(), mouse=SimpleNamespace(wheel=AsyncMock()),
        )
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context

        async def interrupt(*args):
            check_db = sqlite3.connect(storage.DB_PATH)
            try:
                self.assertEqual(storage.load_post(check_db, "1")["post_id"], "1")
            finally:
                check_db.close()
            raise KeyboardInterrupt()

        with patch.object(collector, "browser_context", return_value=manager), \
             patch.object(reader, "human_pause", new=AsyncMock()), \
             patch.object(reader, "expand_see_more", new=AsyncMock()), \
             patch.object(pipeline, "scrape_top_comments", new=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                await collector.main(SimpleNamespace(ocr=False, gpu=False, max_posts=1, comments=0))
        self.assertEqual(len(self.rows()), 1)
        page.close.assert_awaited_once()
        page.mouse.wheel.assert_not_awaited()

    async def test_existing_post_gets_comments_without_losing_images_or_ocr(self):
        db = storage.init_db()
        saved = self.persist(db, self.post(), "test")
        record = storage.load_post(db, saved.post_id)
        record.update(image_files=["ảnh.jpg"], ocr=[{"text": "OCR"}], top_comments=[])
        storage.save_post(db, record)
        db.close()
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context

        async def source(*args):
            yield {"post_id": saved.post_id, "url": saved.url}

        with patch.object(collector, "browser_context", return_value=manager), \
             patch.object(pipeline, "iter_source_posts", new=source), \
             patch.object(pipeline, "scrape_top_comments", new=AsyncMock(return_value=["Bình luận A", "Bình luận B"])), \
             patch.object(pipeline, "download_images", new=AsyncMock()) as download:
            await collector.main(SimpleNamespace(ocr=False, gpu=False, max_posts=1, comments=20))
        row = self.rows()[0]
        self.assertEqual(row["top_comments"], ["Bình luận A", "Bình luận B"])
        self.assertEqual(row["image_files"], ["ảnh.jpg"])
        self.assertEqual(row["ocr"], [{"text": "OCR"}])
        self.assertEqual(len(self.rows()), 1)
        download.assert_not_awaited()

    async def test_collector_finishes_when_jsonl_target_remains_locked(self):
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context
        original_replace = Path.replace

        async def source(*args):
            for number in (1, 2):
                post = self.post(number).model_dump()
                post.update(post_id=str(number), links=[], images=[], posted_raw="")
                yield post

        def deny_target(source, target):
            if target == storage.JSONL_PATH:
                raise PermissionError("file locked")
            return original_replace(source, target)

        with patch.object(collector, "browser_context", return_value=manager), \
             patch.object(pipeline, "iter_source_posts", new=source), \
             patch.object(pipeline, "scrape_top_comments", new=AsyncMock(return_value=["Bình luận A"])), \
             patch.object(pipeline, "download_images", new=AsyncMock(return_value=[])), \
             patch.object(Path, "replace", autospec=True, side_effect=deny_target), \
             patch.object(storage_files.time, "sleep"):
            await collector.main(SimpleNamespace(ocr=False, gpu=False, max_posts=2, comments=20))
        page.close.assert_awaited_once()
        db = sqlite3.connect(storage.DB_PATH)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 2)
        self.assertEqual(len((self.data / "posts.pending.jsonl").read_text(encoding="utf-8").splitlines()), 2)
        self.assertTrue(storage.export_jsonl(db))
        self.assertEqual(len(self.rows()), 2)

    async def test_new_comments_survive_image_download_failure(self):
        db = storage.init_db()
        self.addCleanup(db.close)

        async def source(*args):
            yield {"post_id": "1", "url": self.post().url, "text": self.post().text, "images": []}

        async def download(*args):
            self.assertEqual(storage.load_post(db, "1")["top_comments"], ["Comment A"])
            raise RuntimeError("image download interrupted")

        with patch.object(pipeline, "iter_source_posts", new=source), \
             patch.object(pipeline, "scrape_top_comments", new=AsyncMock(return_value=["Comment A"])), \
             patch.object(pipeline, "download_images", new=download):
            await pipeline.collect_source_posts(None, None, db, {}, SimpleNamespace(max_posts=1, comments=20))
        self.assertEqual(storage.load_post(db, "1")["top_comments"], ["Comment A"])

    async def test_downloaded_images_survive_ocr_failure(self):
        db = storage.init_db()
        self.addCleanup(db.close)

        async def source(*args):
            yield {"post_id": "1", "url": self.post().url, "text": self.post().text, "images": ["image-url"]}

        ocr = SimpleNamespace(read=Mock(side_effect=RuntimeError("OCR failed")))
        with patch.object(pipeline, "iter_source_posts", new=source), \
             patch.object(pipeline, "scrape_top_comments", new=AsyncMock(return_value=[])), \
             patch.object(pipeline, "download_images", new=AsyncMock(return_value=["downloaded.jpg"])):
            await pipeline.collect_source_posts(None, None, db, {}, SimpleNamespace(max_posts=1, comments=0), ocr=ocr)
        self.assertEqual(storage.load_post(db, "1")["image_files"], ["downloaded.jpg"])
        self.assertEqual(storage.load_post(db, "1")["ocr"], [])


if __name__ == "__main__":
    unittest.main()
