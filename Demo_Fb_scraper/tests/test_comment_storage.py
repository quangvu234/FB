"""Quan hệ bình luận qua SQLite, JSONL, dữ liệu cũ và cập nhật từng phần."""
import json
import base64
import sqlite3
from contextlib import closing
import unittest
from unittest.mock import AsyncMock, patch

from fb_scraper.common.comments import Comment, merge_comment_records, needs_comment_refresh
from fb_scraper.common.models import CollectionOptions, Post
from fb_scraper.posts import pipeline
from fb_scraper.storage import database as storage
from tests.persistence_fixtures import PersistenceFixture


class CommentStorageTests(PersistenceFixture, unittest.IsolatedAsyncioTestCase):
    def database(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        return db

    def test_thread_roundtrip_and_same_text_with_different_ids(self):
        db = self.database()
        comments = [
            {"comment_id": "10", "text": "Quan tâm", "is_reply": False, "author": "A"},
            {"comment_id": "11", "parent_comment_id": "10", "root_comment_id": "10", "text": "Quan tâm", "author": "B"},
            {"comment_id": "12", "parent_comment_id": "11", "root_comment_id": "10", "text": "Reply cấp 2"},
        ]
        storage.save_post(db, {"post_id": "1", "top_comments": comments})
        storage.save_post(db, {"post_id": "1", "text": "Cập nhật bài"})
        storage.export_jsonl(db)
        records = self.rows()[0]["top_comments"]
        self.assertEqual(records, storage.load_post(db, "1")["top_comments"])
        self.assertEqual([item["comment_id"] for item in records], ["10", "11", "12"])
        self.assertEqual(records[2]["parent_comment_id"], "11")
        self.assertEqual(records[2]["root_comment_id"], "10")
        self.assertTrue(records[2]["is_reply"])
        self.assertEqual(records[0]["root_comment_id"], "10")

    def test_old_sqlite_strings_export_without_inventing_relationships(self):
        legacy = ["A\nNội dung cũ\nTrả lời"]
        self.data.mkdir(parents=True)
        db = sqlite3.connect(storage.DB_PATH)
        db.execute("CREATE TABLE posts(post_id TEXT PRIMARY KEY, top_comments TEXT)")
        db.execute("INSERT INTO posts(post_id, top_comments) VALUES (?, ?)", ("1", json.dumps(legacy)))
        db.commit()
        db.close()
        db = self.database()
        storage.export_jsonl(db)
        comment = self.rows()[0]["top_comments"][0]
        self.assertEqual(comment["text"], legacy[0])
        for field in ("comment_id", "parent_comment_id", "root_comment_id", "is_reply", "author"):
            self.assertIsNone(comment[field])
        self.assertTrue(needs_comment_refresh([comment], 1))
        backup = next(self.data.glob("posts.before-v3-*.db"))
        with closing(sqlite3.connect(backup)) as original:
            self.assertEqual(json.loads(original.execute("SELECT top_comments FROM posts").fetchone()[0]), legacy)

    def test_agent_model_accepts_legacy_and_structured_comments(self):
        post = Post.model_validate({"top_comments": ["Legacy", {"comment_id": "2", "text": "Reply", "is_reply": True}]})
        self.assertEqual(post.top_comments[0].text, "Legacy")
        self.assertIsNone(post.top_comments[0].is_reply)
        schema = Post.model_json_schema()
        self.assertIn("parent_comment_id", schema["$defs"]["Comment"]["properties"])

    def test_merge_preserves_relationship_and_expanded_text(self):
        old = [{"comment_id": "2", "text": "Nội dung đầy đủ", "parent_comment_id": "1", "root_comment_id": "1"}]
        new = [{"comment_id": "2", "text": "Nội dung…", "is_reply": True}]
        merged = merge_comment_records(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "Nội dung đầy đủ")
        self.assertEqual(merged[0]["parent_comment_id"], "1")

    def test_no_id_same_text_from_different_threads_is_not_merged(self):
        merged = merge_comment_records([
            {"text": "OK", "author": "A", "root_comment_id": "1", "is_reply": True},
            {"text": "OK", "author": "A", "root_comment_id": "2", "is_reply": True},
        ])
        self.assertEqual(len(merged), 2)
        with self.assertRaises(ValueError):
            Comment(comment_id="1", parent_comment_id="1")

    def test_sparse_update_same_id_keeps_parent_and_other_comments(self):
        db = self.database()
        storage.save_post(db, {"post_id": "1", "top_comments": [
            {"comment_id": "10", "text": "Root", "is_reply": False},
            {"comment_id": "11", "text": "Reply", "parent_comment_id": "10", "root_comment_id": "10"},
        ]})
        storage.save_post(db, {"post_id": "1", "top_comments": [{"comment_id": "11", "text": "Reply cập nhật"}]})
        comments = storage.load_post(db, "1")["top_comments"]
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[1]["parent_comment_id"], "10")
        self.assertEqual(comments[1]["text"], "Reply cập nhật")

    def test_complete_comment_count_still_refreshes_missing_author_or_shortened_text(self):
        self.assertTrue(needs_comment_refresh([{"comment_id": "10", "is_reply": False, "text": "Full"}], 1))
        self.assertTrue(needs_comment_refresh([{"comment_id": "10", "is_reply": False,
                                                "author": "A", "text": "Short… Xem thêm"}], 1))
        self.assertFalse(needs_comment_refresh([{"comment_id": "10", "is_reply": False,
                                                 "author": "A", "text": "Full"}], 1))

    def test_legacy_global_id_and_numeric_id_merge_without_duplicate(self):
        global_id = base64.b64encode(b"comment:100_10").decode()
        reply_id = base64.b64encode(b"comment:100_11").decode()
        old = [{"comment_id": global_id, "is_reply": False, "text": "Root"},
               {"comment_id": reply_id, "parent_comment_id": global_id,
                "root_comment_id": global_id, "text": "Reply"}]
        merged = merge_comment_records(old, [{"comment_id": "10", "author": "A", "text": "Root"}])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["author"], "A")
        self.assertEqual(merged[1]["comment_id"], "11")
        self.assertEqual(merged[1]["parent_comment_id"], "10")
        self.assertEqual(merged[1]["root_comment_id"], "10")

    async def test_full_legacy_list_is_refreshed_and_existing_records_survive(self):
        db = self.database()
        storage.save_post(db, {"post_id": "1", "url": self.post().url, "top_comments": ["Legacy"]})

        async def source(*args):
            yield {"post_id": "1", "url": self.post().url}

        fresh = [{"comment_id": "2", "root_comment_id": "1", "is_reply": True, "text": "Reply"}]
        with patch.object(pipeline, "iter_source_posts", new=source), \
             patch.object(pipeline, "scrape_top_comments", new=AsyncMock(return_value=fresh)) as scrape:
            await pipeline.collect_source_posts(None, None, db, {}, CollectionOptions(max_posts=1, max_comments=1))
        scrape.assert_awaited_once()
        comments = storage.load_post(db, "1")["top_comments"]
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0]["text"], "Legacy")
        self.assertEqual(comments[1]["root_comment_id"], "1")


if __name__ == "__main__":
    unittest.main()
