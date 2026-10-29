"""Tìm cá nhân/nhóm theo từ khóa rồi chạy crawler tương ứng ở chế độ info-only.

python main.py search "Nguyễn Văn A" --type profile --max-results 20
python main.py search "Python Việt Nam" --type group --max-results 20
"""
import argparse
import asyncio
import sys
from urllib.parse import urlparse

from fb_scraper.browser.connection import browser_context
from fb_scraper.entities.collector import collect_entities
from fb_scraper.common.models import CollectionOptions
from fb_scraper.search.reader import iter_keyword_results
from fb_scraper.storage import database as storage
# Kiểm tra từ khóa/giới hạn trước khi kết nối Chrome và loại từ khóa nhập trùng.
def validate_args(args):
    """Kiểm tra giới hạn và chuẩn hóa danh sách từ khóa trước khi mở Chrome."""
    if args.max_results < 0 or args.max_scrolls < 0:
        raise ValueError("--max-results và --max-scrolls phải từ 0 trở lên.")
    if args.type not in {"profile", "group", "both"}:
        raise ValueError("--type phải là profile, group hoặc both.")

    keywords = []
    seen_keywords = set()

    for original_keyword in args.keywords:
        keyword = " ".join(original_keyword.split())
        if not keyword:
            continue

        identity = keyword.casefold()
        if identity not in seen_keywords:
            seen_keywords.add(identity)
            keywords.append(keyword)

    if not keywords:
        raise ValueError("Cần nhập ít nhất một từ khóa không rỗng.")

    return keywords


# Tìm kiếm và đọc thông tin trong cùng kết nối Chrome và database.
async def main(args):
    """Tìm URL, lưu nhật ký và đọc thông tin đối tượng trong cùng một phiên Chrome."""
    keywords = validate_args(args)

    if args.type == "both":
        kinds = ["profile", "group"]
    else:
        kinds = [args.type]

    # Mỗi loại có dictionary URL riêng để cùng một URL chỉ được thu thập một lần.
    targets = {}
    for kind in kinds:
        targets[kind] = {}

    db = storage.init_db()
    try:
        async with browser_context() as context:
            page = await context.new_page()
            try:
                for keyword in keywords:
                    for kind in kinds:
                        try:
                            results = iter_keyword_results(
                                page, keyword, kind, args.max_results, args.max_scrolls,
                            )

                            async for result in results:
                                storage.save_search_result(db, result)

                                identity = result["url"].casefold()
                                if identity not in targets[kind]:
                                    targets[kind][identity] = result["url"]

                                print(f"  Tìm thấy: {result['name']} -> {result['url']}", flush=True)

                        except Exception as error:
                            print(f"  Lỗi tìm {kind} ({type(error).__name__}): {error}", flush=True)
                            current_path = urlparse(page.url).path
                            if "/login" in current_path or "/checkpoint" in current_path:
                                return
            finally:
                await page.close()

            options = CollectionOptions(info_only=True, max_posts=0)
            for kind in kinds:
                urls = list(targets[kind].values())
                if urls:
                    await collect_entities(context, urls, kind, options, db=db)
                else:
                    print(f"Không tìm thấy URL {kind} để thu thập thông tin.", flush=True)
    finally:
        try:
            storage.export_search_results(db)
            for kind in kinds:
                storage.export_entities(db, kind)
            storage.export_jsonl(db)
        finally:
            db.close()


# Lệnh mới nhận từ khóa thay cho URL; mọi kết quả luôn được thu thập ở chế độ info-only.
def argument_parser():
    parser = argparse.ArgumentParser(description="Tìm trang cá nhân/nhóm theo từ khóa và thu thập thông tin giới thiệu.")
    parser.add_argument("keywords", nargs="+", metavar="KEYWORD", help="một hoặc nhiều từ khóa; đặt từ khóa có khoảng trắng trong dấu ngoặc kép")
    parser.add_argument("--type", choices=("profile", "group", "both"), default="both", help="loại cần tìm; mặc định both")
    parser.add_argument("--max-results", type=int, default=20, help="URL tối đa mỗi từ khóa/mỗi loại; 0 để lấy đến khi hết kết quả hoặc hết lượt cuộn")
    parser.add_argument("--max-scrolls", type=int, default=30, help="số lần cuộn tối đa mỗi tìm kiếm; mặc định 30")
    return parser


def run_cli(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argument_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(main(args))
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"LỖI: {exc}\n")


if __name__ == "__main__":
    run_cli()
