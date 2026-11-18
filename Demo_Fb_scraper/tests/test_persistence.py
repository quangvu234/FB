"""Kiểm tra SQLite, xuất snapshot, khóa file và migration dữ liệu cũ."""
import unittest
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from fb_scraper.common.comments import normalize_comments
from fb_scraper.storage import database as storage
from fb_scraper.storage import files as storage_files
from tests.persistence_fixtures import PersistenceFixture


class StoragePersistenceTests(PersistenceFixture, unittest.IsolatedAsyncioTestCase):
    async def test_explicit_snapshot_uses_project_path(self):
        old_cwd = Path.cwd()
        try:
            os.chdir(self.temporary.name)
            db = storage.init_db()
            self.addCleanup(db.close)
            self.persist(db, self.post(), "test")
            self.assertEqual(self.rows()[0]["post_id"], "1")
            self.assertEqual(self.rows()[0]["author"], "Tác giả")
            self.assertFalse((Path.cwd() / "data").exists())
            self.persist(db, self.post(), "test")
            self.persist(db, self.post(2), "test")
            self.assertEqual(len(self.rows()), 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 2)
        finally:
            os.chdir(old_cwd)

    async def test_failed_export_keeps_previous_jsonl_and_committed_database(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        self.persist(db, self.post(), "test")
        original = storage.JSONL_PATH.read_bytes()
        original_replace = Path.replace

        def deny_target(source, target):
            if target == storage.JSONL_PATH:
                raise PermissionError("file locked")
            return original_replace(source, target)

        with patch.object(Path, "replace", autospec=True, side_effect=deny_target), \
             patch.object(storage_files.time, "sleep"):
            self.persist(db, self.post(2), "test")
            self.persist(db, self.post(3), "test")
        self.assertEqual(storage.JSONL_PATH.read_bytes(), original)
        pending = self.data / "posts.pending.jsonl"
        self.assertEqual(len(pending.read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 3)
        storage.export_jsonl(db)
        self.assertEqual(len(self.rows()), 3)
        self.assertFalse(pending.exists())

    async def test_transient_windows_lock_is_retried_and_export_succeeds(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        self.persist(db, self.post(), "test")
        original_replace = Path.replace
        failures = 0

        def temporary_lock(source, target):
            nonlocal failures
            if target == storage.JSONL_PATH and failures < 2:
                failures += 1
                raise PermissionError("file temporarily locked")
            return original_replace(source, target)

        with patch.object(Path, "replace", autospec=True, side_effect=temporary_lock), \
             patch.object(storage_files.time, "sleep") as sleep:
            self.persist(db, self.post(2), "test")
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(list(self.data.glob(".posts-*.jsonl.tmp")), [])

    @unittest.skipUnless(os.name == "nt", "Kiểm tra khóa file thực tế chỉ dành cho Windows.")
    async def test_real_windows_file_handle_defers_export_without_crashing(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        self.persist(db, self.post(), "test")
        with storage.JSONL_PATH.open("rb") as locked, patch.object(storage_files.time, "sleep"):
            original = locked.read()
            self.persist(db, self.post(2), "test")
            self.assertEqual(storage.JSONL_PATH.read_bytes(), original)
            self.assertTrue((self.data / "posts.pending.jsonl").exists())
        self.assertTrue(storage.export_jsonl(db))
        self.assertEqual(len(self.rows()), 2)

    async def test_no_writable_snapshot_keeps_database_and_returns_failure(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        self.persist(db, self.post(), "test")
        original = storage.JSONL_PATH.read_bytes()
        with patch.object(storage_files.tempfile, "mkstemp", side_effect=PermissionError("directory locked")):
            self.persist(db, self.post(2), "test")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 2)
        self.assertEqual(storage.JSONL_PATH.read_bytes(), original)

    def test_saves_commit_without_snapshots_and_updates_preserve_omitted_fields(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        with patch.object(storage, "export_rows", wraps=storage.export_rows) as snapshot:
            storage.save_post(db, {"post_id": "1", "text": "Original", "author": "Author", "images": ["image"],
                                   "top_comments": ["Comment"], "entity_type": "profile", "entity_id": "u_test"})
            for number in range(2, 32):
                storage.save_post(db, {"post_id": str(number), "text": "Text"})
            storage.save_post(db, {"post_id": "1", "text": "Updated"})
            snapshot.assert_not_called()
            self.assertFalse(storage.JSONL_PATH.exists())
            check = sqlite3.connect(storage.DB_PATH)
            try:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 31)
            finally:
                check.close()
            storage.export_jsonl(db)
            self.assertEqual(snapshot.call_count, 4)
        row = self.rows()[0]
        self.assertEqual(row["text"], "Updated")
        self.assertEqual(row["author"], "Author")
        self.assertEqual(row["top_comments"], normalize_comments(["Comment"]))
        self.assertEqual(row["images"], ["image"])
        self.assertEqual(row["entity_id"], "u_test")

    def test_legacy_search_history_is_imported_once_and_keeps_duplicates(self):
        self.data.mkdir(parents=True)
        path = self.data / "search_results.jsonl"
        result = {"keyword": "Test", "entity_type": "profile", "name": "Name", "url": "https://www.facebook.com/test",
                  "search_url": "https://www.facebook.com/search/people/?q=Test", "found_at": "2026-10-21T00:00:00+00:00"}
        path.write_text((json.dumps(result) + "\n") * 2, encoding="utf-8")
        db = storage.init_db()
        try:
            self.assertEqual(sum(len(json.loads(row[0]).get("search_history", []))
                                 for row in db.execute("SELECT metadata FROM sources")), 2)
            storage.save_search_result(db, result)
            storage.export_search_results(db)
        finally:
            db.close()
        db = storage.init_db()
        self.addCleanup(db.close)
        self.assertEqual(sum(len(json.loads(row[0]).get("search_history", []))
                             for row in db.execute("SELECT metadata FROM sources")), 3)
        sources = [json.loads(line) for line in (self.data / "sources.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(sources[0]["metadata"]["search_history"]), 3)
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_invalid_legacy_journal_stops_migration_without_overwriting_history(self):
        self.data.mkdir(parents=True)
        path = self.data / "search_results.jsonl"
        path.write_text('broken JSON\n', encoding="utf-8")
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "giữ nguyên file"):
                storage.init_db()
            check = sqlite3.connect(storage.DB_PATH)
            try:
                self.assertIsNone(check.execute("SELECT 1 FROM sqlite_master WHERE name='search_results'").fetchone())
            finally:
                check.close()
            self.assertEqual(path.read_text(encoding="utf-8"), "broken JSON\n")


if __name__ == "__main__":
    unittest.main()
