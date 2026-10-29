"""Lưu SQLite và JSONL tại thư mục data cạnh main.py."""
import json
import sqlite3
from datetime import datetime, timezone

from fb_scraper.common.models import Post, SearchResult
from fb_scraper.common.paths import PROJECT_ROOT
from fb_scraper.storage.entities import ENTITY_COLUMNS, ENTITY_JSON_FIELDS, save_entity
from fb_scraper.storage.files import atomic_write, export_rows

DATA = PROJECT_ROOT / "data"
IMG_DIR = DATA / "images"
DB_PATH = DATA / "posts.db"
JSONL_PATH = DATA / "posts.jsonl"

COLUMNS = (
    "post_id", "url", "source", "author", "text", "posted_raw", "posted_at",
    "likes", "comments", "shares", "links", "images", "image_files", "ocr",
    "top_comments", "collected_at",
    "entity_type", "entity_id",
)

POST_JSON_FIELDS = ("links", "images", "image_files", "ocr", "top_comments")
SEARCH_COLUMNS = ("keyword", "entity_type", "name", "url", "search_url", "found_at")


def init_db():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    try:
        db.execute("BEGIN")
        db.execute("""CREATE TABLE IF NOT EXISTS posts(
            post_id TEXT PRIMARY KEY, url TEXT, source TEXT, author TEXT, text TEXT,
            posted_raw TEXT, posted_at TEXT, likes INT, comments INT, shares INT,
            links TEXT, images TEXT, image_files TEXT, ocr TEXT, top_comments TEXT,
            collected_at TEXT, entity_type TEXT, entity_id TEXT)""")
        # Nâng cấp database đã có; giữ toàn bộ bài viết và bình luận hiện tại.
        existing = set()
        for column in db.execute("PRAGMA table_info(posts)"):
            existing.add(column[1])
        for column in ("entity_type", "entity_id"):
            if column not in existing:
                db.execute(f"ALTER TABLE posts ADD COLUMN {column} TEXT")
        db.execute("""CREATE TABLE IF NOT EXISTS profiles(
            entity_id TEXT PRIMARY KEY, profile_id TEXT, url TEXT, source_url TEXT, about_url TEXT,
            name TEXT, account_type TEXT, bio TEXT, followers_count INTEGER, followers_raw TEXT,
            work TEXT, education TEXT, current_city TEXT, hometown TEXT, collection_status TEXT, collected_at TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS groups(
            entity_id TEXT PRIMARY KEY, group_id TEXT, url TEXT, source_url TEXT, about_url TEXT,
            name TEXT, description TEXT, privacy TEXT, members_count INTEGER, members_raw TEXT,
            rules TEXT, collection_status TEXT, collected_at TEXT)""")
        had_search_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_results'").fetchone()
        db.execute("""CREATE TABLE IF NOT EXISTS search_results(
            result_id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL, entity_type TEXT NOT NULL,
            name TEXT NOT NULL, url TEXT NOT NULL, search_url TEXT NOT NULL, found_at TEXT NOT NULL)""")
        # Import the old append-only journal once; preserve repeated search events.
        legacy = DATA / "search_results.jsonl"
        try:
            if not had_search_table and legacy.exists():
                with legacy.open(encoding="utf-8-sig") as source:
                    for line in source:
                        if line.strip():
                            validated_result = SearchResult.model_validate_json(line)
                            result = validated_result.model_dump()
                            _insert_search_result(db, result)
        except (OSError, ValueError):
            raise RuntimeError("Không nhập được search_results.jsonl cũ; giữ nguyên file để kiểm tra.") from None
        db.commit()
    except BaseException:
        db.close()
        raise
    return db


def export_jsonl(db):
    return export_rows(db, JSONL_PATH, "SELECT * FROM posts ORDER BY rowid", POST_JSON_FIELDS)




def save_post(db, post: dict):
    """Commit một bài vào SQLite. Hàm này chưa xuất lại toàn bộ JSONL."""
    validated_post = Post.model_validate(post)

    # exclude_unset=True: chỉ lấy trường mà bên gọi thực sự truyền vào.
    # Ví dụ chỉ cập nhật bình luận thì không xóa ảnh/OCR đã lưu từ trước.
    incoming_fields = validated_post.model_dump(exclude_unset=True)
    if not incoming_fields.get("post_id"):
        raise ValueError("Bài viết phải có post_id trước khi lưu.")

    previous_record = load_post(db, incoming_fields["post_id"])
    if previous_record is None:
        previous_record = {}

    merged_record = {}
    for field, value in previous_record.items():
        if value is not None:
            merged_record[field] = value

    for field, value in incoming_fields.items():
        merged_record[field] = value

    validated_record = Post.model_validate(merged_record)
    record = validated_record.model_dump()
    record["collected_at"] = datetime.now(timezone.utc).isoformat()

    for field in POST_JSON_FIELDS:
        record[field] = json.dumps(record[field], ensure_ascii=False)

    # Tên cột lấy từ hằng số của project; dữ liệu đi qua dấu ? để SQLite tự xử lý.
    placeholders = []
    values = []
    update_assignments = []

    for column in COLUMNS:
        placeholders.append("?")
        values.append(record.get(column))

        if column != "post_id":
            update_assignments.append(f"{column}=excluded.{column}")

    column_sql = ",".join(COLUMNS)
    placeholder_sql = ",".join(placeholders)
    update_sql = ",".join(update_assignments)
    query = (
        f"INSERT INTO posts({column_sql}) VALUES({placeholder_sql}) "
        f"ON CONFLICT(post_id) DO UPDATE SET {update_sql}"
    )

    # with db commit khi thành công, rollback khi có lỗi; không đóng kết nối db.
    with db:
        db.execute(query, values)


# Xuất thông tin đối tượng; JSONL chứa mảng work/education/rules đúng kiểu JSON.
def export_entities(db, kind):
    """Xuất bảng profiles hoặc groups; các trường danh sách trở thành mảng JSON."""
    if kind not in ENTITY_COLUMNS:
        raise ValueError("Loại đối tượng phải là profile hoặc group.")

    if kind == "profile":
        table_name = "profiles"
    else:
        table_name = "groups"

    target_path = DATA / f"{table_name}.jsonl"
    query = f"SELECT * FROM {table_name} ORDER BY rowid"
    json_fields = ENTITY_JSON_FIELDS[kind]
    return export_rows(db, target_path, query, json_fields)




def _insert_search_result(db, record):
    """Chuẩn bị câu INSERT theo đúng thứ tự cột của nhật ký tìm kiếm."""
    placeholders = []
    values = []

    for column in SEARCH_COLUMNS:
        placeholders.append("?")
        values.append(record[column])

    column_sql = ",".join(SEARCH_COLUMNS)
    placeholder_sql = ",".join(placeholders)
    query = f"INSERT INTO search_results({column_sql}) VALUES({placeholder_sql})"
    db.execute(query, values)


def save_search_result(db, result):
    validated_result = SearchResult.model_validate(result)
    record = validated_result.model_dump()

    with db:
        _insert_search_result(db, record)


def export_search_results(db):
    return export_rows(db, DATA / "search_results.jsonl",
                        f"SELECT {','.join(SEARCH_COLUMNS)} FROM search_results ORDER BY result_id")


def export_agent_output(posts):
    """Xuất các bài của lượt agent hiện tại bằng cùng cơ chế xử lý khóa file."""
    target_path = DATA / "data_agent.json"
    post_records = []

    for post in posts:
        if isinstance(post, Post):
            validated_post = post
        else:
            validated_post = Post.model_validate(post)

        post_records.append(validated_post.model_dump())

    payload = {"posts": post_records}

    def write_output(output):
        json.dump(payload, output, ensure_ascii=False, indent=2)

    return atomic_write(target_path, write_output)


def known_ids(db):
    """Lấy tập ID để collector kiểm tra bài đã có mà không phải đọc lại từng bài."""
    post_ids = set()
    cursor = db.execute("SELECT post_id FROM posts")

    for row in cursor:
        post_ids.add(row[0])

    return post_ids


def load_post(db, post_id):
    """Đọc một bài SQLite và đổi các cột JSON dạng TEXT về danh sách Python."""
    cursor = db.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,))
    row = cursor.fetchone()

    if row is None:
        return None

    record = {}
    for index in range(len(cursor.description)):
        column_name = cursor.description[index][0]
        record[column_name] = row[index]

    for field in POST_JSON_FIELDS:
        stored_value = record.get(field)
        if not stored_value:
            stored_value = "[]"

        record[field] = json.loads(stored_value)

    return record


def print_storage_paths():
    print("Thư mục dữ liệu:", DATA, flush=True)
    print("JSONL:", JSONL_PATH, flush=True)
    print("SQLite:", DB_PATH, flush=True)


def run_cli(argv=None):
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Xuất lại JSONL từ SQLite, không chạy trình duyệt.")
    parser.add_argument("--export-jsonl", action="store_true", help="xuất bài viết, trang cá nhân và nhóm từ data/posts.db")
    args = parser.parse_args(argv)
    if not args.export_jsonl:
        parser.print_help()
    else:
        db = init_db()
        try:
            exported = export_jsonl(db)
            if exported:
                count_cursor = db.execute("SELECT COUNT(*) FROM posts")
                post_count = count_cursor.fetchone()[0]
                print(f"Đã xuất {post_count} bài -> {JSONL_PATH}")
            for kind in ("profile", "group"):
                result = export_entities(db, kind)
                if not result:
                    exported = False
                if result:
                    if kind == "profile":
                        table = "profiles"
                    else:
                        table = "groups"
                    count_query = f"SELECT COUNT(*) FROM {table}"
                    count_cursor = db.execute(count_query)
                    entity_count = count_cursor.fetchone()[0]
                    output_path = DATA / (table + ".jsonl")
                    print(f"Đã xuất {entity_count} đối tượng -> {output_path}")
            search_exported = export_search_results(db)
            if not search_exported:
                exported = False
        finally:
            db.close()
        exit_code = 1
        if exported:
            exit_code = 0
        raise SystemExit(exit_code)


if __name__ == "__main__":
    run_cli()
