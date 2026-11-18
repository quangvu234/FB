"""Migration bảo toàn dữ liệu cũ, rollback khi lỗi và mở được SQL chuẩn người dùng."""
from contextlib import closing
import json
import sqlite3
import unittest

from fb_scraper.storage import database as storage
from fb_scraper.storage.records import post_record
from tests.persistence_fixtures import PersistenceFixture

LEGACY_POSTS = '''CREATE TABLE posts(post_id TEXT PRIMARY KEY, url TEXT, source TEXT, author TEXT,
text TEXT, posted_raw TEXT, posted_at TEXT, likes INTEGER, comments INTEGER, shares INTEGER,
links TEXT, images TEXT, image_files TEXT, ocr TEXT, top_comments TEXT, collected_at TEXT,
entity_type TEXT, entity_id TEXT)'''


class SchemaMigrationTests(PersistenceFixture, unittest.TestCase):
    def legacy_db(self, comments):
        self.data.mkdir(parents=True)
        db = sqlite3.connect(storage.DB_PATH)
        db.execute(LEGACY_POSTS)
        db.execute("CREATE TABLE profiles(entity_id TEXT PRIMARY KEY,url TEXT,name TEXT,account_type TEXT,work TEXT)")
        db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)",
                   ("u_page", "https://www.facebook.com/example", "Trang mẫu", "page", '["Work"]'))
        db.execute("INSERT INTO posts(post_id,url,source,author,text,images,image_files,ocr,top_comments,collected_at,entity_type,entity_id) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("p", "https://www.facebook.com/example/posts/123", "kw:test", "Author", "Full original text",
                    '["https://example.org/image.jpg"]', '["saved.jpg"]', '[{"text":"OCR"}]', json.dumps(comments),
                    "2026-01-01T00:00:00+00:00", "profile", "u_page"))
        db.commit()
        db.close()

    def test_migrates_names_full_content_entities_comments_media_and_timestamps(self):
        self.legacy_db([{"comment_id": "a", "author": "A", "text": "Root", "is_reply": False},
                        {"comment_id": "b", "author": "B", "text": "Reply", "parent_comment_id": "a", "root_comment_id": "a"}])
        db = storage.init_db()
        self.addCleanup(db.close)
        record = post_record(db, "p")
        self.assertEqual(record["content"], "Full original text")
        self.assertEqual(record["author"], "Author")
        self.assertEqual(record["collected_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(record["last_seen_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(record["source_record"]["source_type"], "page")
        self.assertEqual(record["source_record"]["metadata"]["entity"]["work"], ["Work"])
        self.assertEqual(record["comments"][1]["author"], "B")
        self.assertEqual(record["comments"][1]["parent_comment_id"], record["comments"][0]["id"])
        self.assertEqual(record["media"][0]["ocr_text"], "OCR")
        self.assertEqual(record["media"][0]["file_path"], "saved.jpg")
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        backup = next(self.data.glob("posts.before-v3-*.db"))
        with closing(sqlite3.connect(backup)) as old:
            self.assertEqual(old.execute("SELECT text FROM posts").fetchone()[0], "Full original text")
        db.close()
        again = storage.init_db()
        self.addCleanup(again.close)
        self.assertEqual(again.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 2)
        self.assertEqual(len(list(self.data.glob("posts.before-v3-*.db"))), 1)

    def test_failed_migration_rolls_back_ddl_and_preserves_original(self):
        self.legacy_db([{"comment_id": "a", "parent_comment_id": "b", "text": "A"},
                        {"comment_id": "b", "parent_comment_id": "a", "text": "B"}])
        with self.assertRaises(ValueError):
            storage.init_db()
        with closing(sqlite3.connect(storage.DB_PATH)) as db:
            self.assertEqual(db.execute("SELECT text FROM posts").fetchone()[0], "Full original text")
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='comments'").fetchone())
            self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='profiles'").fetchone())
        self.assertTrue(list(self.data.glob("posts.before-v3-*.db")))

    def test_user_base_schema_is_extended_without_replacing_rows(self):
        self.data.mkdir(parents=True)
        with closing(sqlite3.connect(storage.DB_PATH)) as db:
            db.executescript('''CREATE TABLE sources(id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL CHECK(source_type IN ('profile','page','group')),
                source_label TEXT NOT NULL,source_ref TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,last_checked_at TEXT);
                CREATE TABLE posts(id INTEGER PRIMARY KEY AUTOINCREMENT,source_id INTEGER NOT NULL,
                post_key TEXT NOT NULL UNIQUE,content TEXT,posted_at TEXT,is_shared INTEGER NOT NULL DEFAULT 0,
                original_post_key TEXT,collected_at TEXT DEFAULT CURRENT_TIMESTAMP,last_seen_at TEXT,
                FOREIGN KEY(source_id) REFERENCES sources(id));
                CREATE TABLE comments(id INTEGER PRIMARY KEY AUTOINCREMENT,post_id INTEGER NOT NULL,parent_comment_id INTEGER,
                comment_key TEXT NOT NULL UNIQUE,content TEXT,created_at TEXT,reaction_count INTEGER DEFAULT 0,
                collected_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(post_id) REFERENCES posts(id),
                FOREIGN KEY(parent_comment_id) REFERENCES comments(id));
                CREATE TABLE media(id INTEGER PRIMARY KEY AUTOINCREMENT,post_id INTEGER,comment_id INTEGER,
                media_type TEXT NOT NULL CHECK(media_type IN ('image','video','gif')),file_path TEXT,file_hash TEXT,
                ocr_text TEXT,position INTEGER DEFAULT 0,FOREIGN KEY(post_id) REFERENCES posts(id),
                FOREIGN KEY(comment_id) REFERENCES comments(id),
                CHECK((post_id IS NOT NULL AND comment_id IS NULL) OR (post_id IS NULL AND comment_id IS NOT NULL)));
                INSERT INTO sources(id,source_type,source_label) VALUES(1,'page','Page');
                INSERT INTO posts(id,source_id,post_key,content) VALUES(1,1,'p','Full text');
                INSERT INTO comments(id,post_id,comment_key,content) VALUES(1,1,'root','Root');
                INSERT INTO comments(id,post_id,parent_comment_id,comment_key,content) VALUES(2,1,1,'reply','Reply');''')
        db = storage.init_db()
        self.addCleanup(db.close)
        record = post_record(db, "p")
        self.assertEqual(record["id"], 1)
        self.assertEqual(record["comments"][1]["parent_comment_key"], "root")
        self.assertEqual(record["comments"][1]["root_comment_key"], "root")
        self.assertEqual(record["comments"][1]["is_reply"], 1)


if __name__ == "__main__":
    unittest.main()
