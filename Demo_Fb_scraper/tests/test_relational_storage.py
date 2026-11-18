"""Khóa ngoại, định danh ổn định, cập nhật từng phần và snapshot của 4 bảng."""
import hashlib
import json
import sqlite3
import unittest

from fb_scraper.storage import database as storage
from fb_scraper.storage.records import post_record
from fb_scraper.storage.media_store import write_media
from tests.persistence_fixtures import PersistenceFixture


class RelationalStorageTests(PersistenceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = storage.init_db()
        self.addCleanup(self.db.close)

    def test_exactly_four_tables_and_foreign_keys_enabled(self):
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        self.assertEqual(tables, {"sources", "posts", "comments", "media"})
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_page_post_and_out_of_order_replies_use_internal_ids(self):
        storage.save_post(self.db, {"post_key": "fb-post", "content": "Bài chia sẻ",
            "source_type": "page", "source_ref": "https://www.facebook.com/example", "source_label": "Trang mẫu",
            "is_shared": True, "original_post_key": "original", "top_comments": [
                {"comment_id": "fb-child", "parent_comment_id": "fb-root", "root_comment_id": "fb-root", "text": "Reply"},
                {"comment_id": "fb-root", "text": "Root", "is_reply": False}]})
        record = post_record(self.db, "fb-post")
        child, root = record["comments"]
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record["source_record"]["source_type"], "page")
        self.assertEqual(child["post_id"], record["id"])
        self.assertEqual(child["parent_comment_id"], root["id"])
        self.assertNotEqual(child["parent_comment_id"], root["comment_key"])
        self.assertEqual(record["original_post_key"], "original")
        self.assertEqual(record["is_shared"], 1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_pending_parent_links_when_parent_arrives_later(self):
        storage.save_post(self.db, {"post_id": "p", "top_comments": [
            {"comment_id": "child", "parent_comment_id": "root", "text": "Child"}]})
        before = post_record(self.db, "p")["comments"][0]
        self.assertIsNone(before["parent_comment_id"])
        self.assertEqual(before["parent_comment_key"], "root")
        storage.save_post(self.db, {"post_id": "p", "top_comments": [{"comment_id": "root", "text": "Root", "is_reply": False}]})
        child, root = post_record(self.db, "p")["comments"]
        self.assertEqual(child["parent_comment_id"], root["id"])
        self.assertEqual(before["id"], child["id"])

    def test_root_thread_is_not_assumed_to_be_immediate_parent(self):
        storage.save_post(self.db, {"post_id": "p", "top_comments": [
            {"comment_id": "root", "text": "Root", "is_reply": False},
            {"comment_id": "reply", "root_comment_id": "root", "is_reply": True, "text": "Reply"}]})
        reply = post_record(self.db, "p")["comments"][1]
        self.assertIsNone(reply["parent_comment_id"])
        self.assertEqual(reply["root_comment_key"], "root")

    def test_cycle_or_cross_post_comment_rolls_back_entire_update(self):
        storage.save_post(self.db, {"post_id": "p", "text": "Original", "top_comments": [{"comment_id": "root", "text": "Root"}]})
        with self.assertRaises(ValueError):
            storage.save_post(self.db, {"post_id": "p", "text": "Broken", "top_comments": [
                {"comment_id": "a", "parent_comment_id": "b", "text": "A"},
                {"comment_id": "b", "parent_comment_id": "a", "text": "B"}]})
        self.assertEqual(storage.load_post(self.db, "p")["text"], "Original")
        with self.assertRaises(ValueError):
            storage.save_post(self.db, {"post_id": "different", "top_comments": [{"comment_id": "root", "text": "Other"}]})
        self.assertIsNone(storage.load_post(self.db, "different"))

    def test_sql_rejects_cross_post_parent_and_invalid_media_owner(self):
        storage.save_post(self.db, {"post_id": "p", "top_comments": [{"comment_id": "root", "text": "Root"}]})
        other = storage.save_post(self.db, {"post_id": "other"})
        comment = post_record(self.db, "p")["comments"][0]
        for query, args in [
            ("INSERT INTO comments(post_id,parent_comment_id,comment_key) VALUES(?,?,?)", (other, comment["id"], "bad")),
            ("INSERT INTO media(media_type) VALUES('image')", ()),
            ("INSERT INTO media(post_id,comment_id,media_type) VALUES(?,?,?)", (other, comment["id"], "image")),
            ("INSERT INTO posts(source_id,post_key) VALUES(?,?)", (999999, "orphan")),
        ]:
            with self.assertRaises(sqlite3.IntegrityError):
                with self.db:
                    self.db.execute(query, args)

    def test_media_hash_ocr_type_order_and_comment_attachment_roundtrip(self):
        path = self.data / "images" / "asset.jpg"
        path.write_bytes(b"fixture-image-bytes")
        storage.save_post(self.db, {"post_id": "p", "images": ["https://example.org/image.jpg"],
            "image_files": [str(path)], "ocr": [{"text": "Chữ trong ảnh", "urls": ["https://example.org"]}],
            "media": [{"media_type": "video", "media_url": "https://example.org/video.mp4", "position": 2}],
            "top_comments": [{"comment_id": "root", "text": "Image comment", "media": [
                {"media_type": "gif", "media_url": "https://example.org/reply.gif", "position": 0}]}]})
        record = post_record(self.db, "p")
        image, video = record["media"]
        self.assertEqual(image["file_hash"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(image["ocr_text"], "Chữ trong ảnh")
        self.assertEqual(video["media_type"], "video")
        self.assertEqual(record["comments"][0]["media"][0]["media_type"], "gif")
        storage.save_post(self.db, {"post_id": "p", "ocr": [{"text": "OCR đầy đủ"}]})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media").fetchone()[0], 3)
        self.assertEqual(storage.load_post(self.db, "p")["image_files"], [str(path)])

    def test_unique_keys_and_first_collected_timestamp_survive_repeated_save(self):
        storage.save_post(self.db, {"post_id": "p", "text": "Content", "top_comments": [{"comment_id": "c", "text": "Comment"}]})
        first = post_record(self.db, "p")
        storage.save_post(self.db, {"post_id": "p", "text": "Full content", "top_comments": [{"comment_id": "c", "author": "A", "text": "Comment"}]})
        last = post_record(self.db, "p")
        self.assertEqual(first["id"], last["id"])
        self.assertEqual(first["collected_at"], last["collected_at"])
        self.assertGreaterEqual(last["last_seen_at"], first["last_seen_at"])
        self.assertEqual(len(last["comments"]), 1)
        self.assertEqual(first["comments"][0]["id"], last["comments"][0]["id"])

    def test_changed_image_url_keeps_download_and_ocr_without_duplicate_media(self):
        storage.save_post(self.db, {"post_id": "p", "images": ["https://example.org/image?token=old"],
            "image_files": ["saved.jpg"], "ocr": [{"text": "Known OCR"}]})
        storage.save_post(self.db, {"post_id": "p", "images": ["https://example.org/image?token=new"]})
        record = post_record(self.db, "p")
        self.assertEqual(len(record["media"]), 1)
        self.assertEqual(record["media"][0]["media_url"], "https://example.org/image?token=new")
        self.assertEqual(record["media"][0]["file_path"], "saved.jpg")
        self.assertEqual(record["media"][0]["ocr_text"], "Known OCR")

    def test_four_snapshots_have_real_database_foreign_keys(self):
        storage.save_post(self.db, {"post_id": "p", "text": "Content", "top_comments": [
            {"comment_id": "root", "text": "Root"}, {"comment_id": "reply", "parent_comment_id": "root", "text": "Reply"}]})
        self.assertTrue(storage.export_jsonl(self.db))
        tables = {table: [json.loads(line) for line in (self.data / (table + ".jsonl")).read_text(encoding="utf-8").splitlines()]
                  for table in ("sources", "posts", "comments", "media")}
        self.assertEqual(tables["posts"][0]["source_id"], tables["sources"][0]["id"])
        self.assertEqual(tables["comments"][1]["parent_comment_id"], tables["comments"][0]["id"])
        self.assertEqual(tables["comments"][0]["post_id"], tables["posts"][0]["id"])


if __name__ == "__main__":
    unittest.main()
