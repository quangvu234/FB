"""
Thu thập bài đăng CÔNG KHAI trên Facebook qua Playwright, gắn vào Chrome thật (CDP).

Bước 1: chạy scripts/open_chrome.ps1 để đăng nhập Facebook trong hồ sơ riêng khi thiết lập.
USE_LOCAL_BROWSER=1 tự mở lại cùng hồ sơ ở các lượt chạy sau.
Bước 2: python main.py posts --keyword "việc làm online tại nhà" --max-posts 30
"""
import argparse
import asyncio
from urllib.parse import urlencode

from fb_scraper.browser.connection import browser_context
from fb_scraper.common.models import CollectionOptions
from fb_scraper.posts.pipeline import collect_source_posts
from fb_scraper.storage.database import export_jsonl, init_db, known_ids, print_storage_paths

# Từ khóa mặc định khi không truyền --keyword; nhập chữ thường, không cần encode.
KEYWORDS = ["việc làm online tại nhà"]


def build_sources(keywords=None):
    """Tạo nguồn tìm bài và tự mã hóa từ khóa thành tham số URL."""
    if keywords is None:
        keywords = KEYWORDS
    sources = []
    for original_keyword in keywords:
        keyword = original_keyword.strip()
        if not keyword:
            raise ValueError("Từ khóa không được rỗng.")
        sources.append({
            "name": f"kw:{keyword}",
            "url": "https://www.facebook.com/search/posts?" + urlencode({"q": keyword}),
        })
    return sources


# Điều phối kết nối Chrome, thu thập bài/bình luận/ảnh/OCR và lưu SQLite cùng JSONL.
# Bổ sung bình luận cho bài đã có; xuất lại JSONL và đóng database khi kết thúc.
async def main(args):
    sources = build_sources(getattr(args, "keywords", None))
    # argparse trả về object; vars() đổi object đó thành dictionary các tùy chọn.
    options = CollectionOptions.model_validate(vars(args))
    db = init_db()
    try:
        print_storage_paths()
        ocr_engine = None
        if options.ocr:
            from fb_scraper.common.ocr import OCREngine
            ocr_engine = OCREngine(gpu=options.gpu)

        known_post_ids = known_ids(db)
        print(f"Đã có {len(known_post_ids)} bài trong SQLite.", flush=True)

        async with browser_context() as context:
            page = await context.new_page()
            try:
                for source in sources:
                    print(f"==> {source['name']}", flush=True)
                    await collect_source_posts(
                        page, context, db, source, options, known_post_ids, ocr_engine,
                    )
            finally:
                await page.close()
    finally:
        try:
            export_jsonl(db)
            total = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            print(f"Tổng bài trong database: {total}", flush=True)
        finally:
            db.close()


def argument_parser():
    parser = argparse.ArgumentParser(description="Thu thập bài viết Facebook công khai.")
    parser.add_argument(
        "--keyword", dest="keywords", action="append", metavar="KEYWORD",
        help="từ khóa tìm bài (tự encode URL); có thể lặp lại để tìm nhiều từ khóa",
    )
    parser.add_argument("--max-posts", type=int, default=20, help="số post tối đa mỗi nguồn")
    parser.add_argument("--comments", dest="max_comments", type=int, default=0,
                        help="số bình luận nổi bật cần lấy cho mỗi post")
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
