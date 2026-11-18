"""Lệnh storage: xuất lại JSONL từ SQLite, không chạy trình duyệt."""
import argparse

from fb_scraper.storage import database as storage


def export_all(db):
    """Xuất sources/posts/comments/media, dùng ID khóa ngoại giống SQLite."""
    exported = storage.export_jsonl(db)
    for table in storage.TABLES:
        print(f"{table}: {storage.count_rows(db, table)} bản ghi -> {storage.DATA / (table + '.jsonl')}")
    return exported


def run_cli(argv=None):
    parser = argparse.ArgumentParser(description="Xuất lại JSONL từ SQLite, không chạy trình duyệt.")
    parser.add_argument("--export-jsonl", action="store_true", help="xuất 4 bảng sources/posts/comments/media từ SQLite")
    args = parser.parse_args(argv)
    if not args.export_jsonl:
        parser.print_help()
        return

    db = storage.init_db()
    try:
        exported = export_all(db)
    finally:
        db.close()
    raise SystemExit(0 if exported else 1)
