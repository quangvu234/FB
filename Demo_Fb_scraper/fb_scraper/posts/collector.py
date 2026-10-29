"""
Thu thập bài đăng CÔNG KHAI trên Facebook qua Playwright, gắn vào Chrome thật (CDP).

Bước 1: chạy scripts/open_chrome.ps1 để đăng nhập Facebook trong hồ sơ riêng khi thiết lập.
USE_LOCAL_BROWSER=1 tự mở lại cùng hồ sơ ở các lượt chạy sau.
Bước 2: python main.py posts --max-posts 30 --comments 5 --ocr
"""
import argparse
import asyncio
import sys

from fb_scraper.browser.connection import browser_context
from fb_scraper.common.models import CollectionOptions
from fb_scraper.posts.pipeline import collect_source_posts
from fb_scraper.storage.database import export_jsonl, init_db, known_ids, print_storage_paths

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

# Nguồn tìm kiếm bài viết cần thu thập.
SOURCES = [
    {"name": "kw:messi", "url": "https://www.facebook.com/search/posts?q=messi"},
]


# Điều phối kết nối Chrome, thu thập bài/bình luận/ảnh/OCR và lưu SQLite cùng JSONL.
# Bổ sung bình luận cho bài đã có; xuất lại JSONL và đóng database khi kết thúc.
async def main(args):
    # argparse trả về object; vars() đổi object đó thành dictionary các tùy chọn.
    command_options = vars(args)
    options = CollectionOptions.model_validate(command_options)
    database = init_db()
    try:
        print_storage_paths()
        ocr_engine = None
        if options.ocr:
            from fb_scraper.common.ocr import OCREngine
            ocr_engine = OCREngine(gpu=options.gpu)

        known_post_ids = known_ids(database)
        print(f"Đã có {len(known_post_ids)} bài trong SQLite.", flush=True)

        async with browser_context() as context:
            page = await context.new_page()
            try:
                for source in SOURCES:
                    print(f"==> {source['name']}", flush=True)
                    await collect_source_posts(
                        page, context, database, source, options, known_post_ids, ocr_engine,
                    )
            finally:
                await page.close()
    finally:
        try:
            export_jsonl(database)
            count_query = database.execute("SELECT COUNT(*) FROM posts")
            total = count_query.fetchone()[0]
            print(f"Tổng bài trong database: {total}", flush=True)
        finally:
            database.close()


# Tạo giao diện dòng lệnh thu thập bài viết.
def argument_parser():
    parser = argparse.ArgumentParser(description="Thu thập bài viết Facebook công khai.")
    parser.add_argument("--max-posts", type=int, default=20, help="số post tối đa mỗi nguồn")
    parser.add_argument("--comments", type=int, default=0, help="số comment nổi bật mỗi post")
    parser.add_argument("--ocr", action="store_true", help="OCR ảnh đính kèm bằng EasyOCR")
    parser.add_argument("--gpu", action="store_true")
    return parser


def run_cli(argv=None):
    parser = argument_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(main(args))
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"LỖI: {exc}\n")


if __name__ == "__main__":
    run_cli()
