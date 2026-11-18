"""SQLite chuẩn hóa: sources → posts → comments/media; commit trước khi xuất snapshot."""
import json
import sqlite3

from fb_scraper.common.models import Post
from fb_scraper.common.paths import PROJECT_ROOT
from fb_scraper.storage.files import atomic_write, export_rows
from fb_scraper.storage.migration import upgrade
from fb_scraper.storage.post_store import write_post
from fb_scraper.storage.records import load_post, post_record
from fb_scraper.storage.schema import TABLES, create_tables
from fb_scraper.storage.source_store import save_entity, write_search_result

DATA = PROJECT_ROOT / "data"
IMG_DIR = DATA / "images"
DB_PATH = DATA / "posts.db"
JSONL_PATH = DATA / "posts.jsonl"


def _create_tables(db):
    create_tables(db)


def init_db():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        upgrade(db, DB_PATH, DATA)
    except BaseException:
        db.close()
        raise
    return db


def save_post(db, post):
    with db:
        return write_post(db, post)


def known_ids(db):
    return {row[0] for row in db.execute("SELECT post_key FROM posts")}


def save_search_result(db, result):
    with db:
        return write_search_result(db, result)


def count_rows(db, table):
    if table not in TABLES:
        raise ValueError("Bảng không thuộc schema hiện tại.")
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def export_sources(db):
    return export_rows(db, DATA / "sources.jsonl", "SELECT * FROM sources ORDER BY id", ("metadata",))


def export_jsonl(db):
    """Xuất 4 snapshot khi kết thúc; posts chứa thêm bản ghi liên quan để đọc thuận tiện."""
    statuses = [export_rows(db, JSONL_PATH, "SELECT * FROM posts ORDER BY id", ("metadata",),
                            transform=lambda row: post_record(db, row["post_key"]))]
    statuses.append(export_sources(db))
    statuses.append(export_rows(db, DATA / "comments.jsonl", "SELECT * FROM comments ORDER BY id"))
    statuses.append(export_rows(db, DATA / "media.jsonl", "SELECT * FROM media ORDER BY id", ("metadata",)))
    return all(statuses)


def entity_jsonl_path(kind):
    if kind not in {"profile", "page", "group"}:
        raise ValueError("Loại nguồn không hợp lệ.")
    return DATA / "sources.jsonl"


def export_entities(db, kind):
    entity_jsonl_path(kind)
    return export_sources(db)


def export_search_results(db):
    return export_sources(db)


def export_agent_output(posts, db=None):
    own_connection = db is None
    if own_connection:
        db = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        payload = {"posts": [post_record(db, Post.model_validate(post).post_id) for post in posts]}
        if any(record is None for record in payload["posts"]):
            raise ValueError("Agent có bài chưa được lưu vào database.")
        return atomic_write(DATA / "data_agent.json", lambda output: json.dump(payload, output, ensure_ascii=False, indent=2))
    finally:
        if own_connection:
            db.close()


def print_storage_paths():
    print("Thư mục dữ liệu:", DATA, flush=True)
    print("JSONL:", JSONL_PATH, flush=True)
    print("SQLite (sources/posts/comments/media):", DB_PATH, flush=True)
