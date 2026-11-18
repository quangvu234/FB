"""Kiểm tra agent lưu bài, giữ dữ liệu khi lỗi và xuất JSON an toàn."""
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fb_scraper.agent import mode as agent_mode
from fb_scraper.storage import database as storage
from fb_scraper.storage import files as storage_files
from tests.persistence_fixtures import PersistenceFixture


class AgentPersistenceTests(PersistenceFixture, unittest.IsolatedAsyncioTestCase):
    async def test_agent_update_preserves_downloaded_images_and_ocr(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        saved = self.persist(db, self.post(), "test")
        record = self.rows()[0]
        record.update({"links": [], "images": [], "image_files": ["ảnh.jpg"], "ocr": [{"text": "OCR"}], "top_comments": []})
        storage.save_post(db, record)
        self.persist(db, agent_mode.Post.model_validate(saved.model_dump()), "test")
        self.assertEqual(self.rows()[0]["image_files"], ["ảnh.jpg"])
        self.assertEqual(self.rows()[0]["ocr"], [{"text": "OCR"}])

    async def test_agent_tool_persists_without_final_result(self):
        result = await self.run_fake_agent("no_final")
        self.assertEqual(len(result.posts), 1)
        self.assertEqual(len(self.rows()), 1)
        agent_json = json.loads((self.data / "data_agent.json").read_text(encoding="utf-8"))
        self.assertEqual(agent_json["posts"][0]["post_key"], "1")

    async def test_agent_partial_data_survives_llm_error(self):
        with self.assertRaisesRegex(RuntimeError, "LLM disconnected"):
            await self.run_fake_agent("error")
        self.assertEqual(len(self.rows()), 1)
        self.assertTrue((self.data / "data_agent.json").is_file())

    async def test_agent_cleanup_failure_preserves_original_error_and_committed_posts(self):
        with self.assertRaisesRegex(RuntimeError, "LLM disconnected"):
            await self.run_fake_agent("error", stop_error=RuntimeError("cleanup failed"))
        self.assertEqual(len(self.rows()), 1)

    async def test_agent_final_only_result_is_also_persisted(self):
        result = await self.run_fake_agent("final_only")
        self.assertEqual(len(result.posts), 1)
        self.assertEqual(len(self.rows()), 1)

    async def test_agent_never_saves_search_page_as_post_url(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        post = self.post().model_copy(update={"url": "https://www.facebook.com/search/posts?q=messi"})
        saved = self.persist(db, post, "kw:messi")
        self.assertEqual(saved.url, "")
        self.assertEqual(self.rows()[0]["url"], "")
        self.assertEqual(saved.text, post.text)

    async def test_locked_agent_json_keeps_pending_output_and_does_not_stop_agent(self):
        target = self.data / "data_agent.json"
        original = Path.replace

        def locked(path, destination):
            if destination == target:
                raise PermissionError("locked")
            return original(path, destination)

        with patch.object(Path, "replace", autospec=True, side_effect=locked), patch.object(storage_files.time, "sleep"):
            result = await self.run_fake_agent("no_final")
        self.assertEqual(len(self.rows()), 1)
        pending = self.data / "data_agent.pending.json"
        self.assertEqual(json.loads(pending.read_text(encoding="utf-8"))["posts"][0]["post_key"], "1")
        self.assertTrue(storage.export_agent_output(result.posts))
        self.assertFalse(pending.exists())


if __name__ == "__main__":
    unittest.main()
