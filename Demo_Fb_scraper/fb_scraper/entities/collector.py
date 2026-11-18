"""Điều phối thu thập thông tin và bài viết cá nhân/nhóm qua CLI."""
import argparse
import asyncio

from fb_scraper.browser.connection import browser_context
from fb_scraper.entities.reader import scrape_entity
from fb_scraper.common.urls import canonical_entity_url
from fb_scraper.common.models import CollectionOptions, ENTITY_MODELS
from fb_scraper.posts import pipeline as post_pipeline
from fb_scraper.storage import database as storage


def validate_sources(urls, kind):
    """Kiểm tra URL trước khi mở Chrome và bỏ các nguồn nhập trùng."""
    if kind not in ENTITY_MODELS:
        raise ValueError("Loại đối tượng phải là profile hoặc group.")

    sources = []
    seen_urls = set()

    for url in urls:
        canonical_url = canonical_entity_url(url, kind)
        if not canonical_url:
            raise ValueError(f"URL {kind} không hợp lệ: {url}")

        if canonical_url not in seen_urls:
            seen_urls.add(canonical_url)
            sources.append(url)

    if not sources:
        raise ValueError("Cần nhập ít nhất một URL để thu thập.")

    return sources


def post_source(entity, kind):
    """Tạo nguồn bài viết cho đối tượng; nhóm chỉ được thu thập khi xác định là Công khai."""
    if kind == "group" and entity["privacy"] != "public":
        print("  Chỉ thu thập bài viết của nhóm được xác định là Công khai.", flush=True)
        return None
    return {"url": entity["url"], "name": f"{kind}:{entity['entity_id']}", "public_only": kind == "profile"}


async def collect_entities(context, urls, kind, options=None, *, db, source_type=None):
    """Đọc thông tin (và bài viết nếu được yêu cầu) của từng URL.

    Bên gọi mở db, xuất snapshot và đóng db; hàm này chỉ ghi vào db.
    Nhờ vậy search và entity dùng chung một kết nối Chrome và một database.
    """
    sources = validate_sources(urls, kind)

    if not options:
        options = CollectionOptions()

    collect_posts = not options.info_only and options.max_posts > 0

    known_post_ids = set()
    ocr_engine = None
    if collect_posts:
        known_post_ids = storage.known_ids(db)
        if options.ocr:
            from fb_scraper.common.ocr import OCREngine
            ocr_engine = OCREngine(gpu=options.gpu)

    page = await context.new_page()
    try:
        for url in sources:
            print(f"==> {kind}:{url}", flush=True)

            try:
                entity = await scrape_entity(page, url, kind)
            except Exception as error:
                print(f"  Lỗi đọc thông tin ({type(error).__name__}): {error}", flush=True)
                continue

            if source_type == "page" and kind == "profile":
                entity["account_type"] = "page"
            source_id = storage.save_entity(db, kind, entity)
            displayed_name = entity["name"] or entity["entity_id"]
            status = entity["collection_status"]
            print(f"  Đã lưu {displayed_name} vào SQLite; trạng thái: {status}", flush=True)

            if not collect_posts:
                continue
            if not entity["name"] or status in {"login_required", "unavailable"}:
                print("  Bỏ qua bài viết: chưa truy cập được thông tin đối tượng.", flush=True)
                continue

            source = post_source(entity, kind)
            if source:
                entity_fields = {"entity_type": kind, "entity_id": entity["entity_id"]}
                entity_fields.update(source_id=source_id, source_ref=entity["url"], source_label=entity["name"],
                                     source_type="page" if entity.get("account_type") == "page" else kind)
                await post_pipeline.collect_source_posts(
                    page, context, db, source, options, known_post_ids, ocr_engine,
                    post_fields=entity_fields,
                )
    finally:
        await page.close()


async def main(args):
    options = CollectionOptions.model_validate(vars(args))
    kind = "profile" if args.type == "page" else args.type
    sources = validate_sources(args.urls, kind)
    db = storage.init_db()
    try:
        async with browser_context() as context:
            await collect_entities(context, sources, kind, options, db=db,
                                   source_type="page" if args.type == "page" else None)
    finally:
        try:
            storage.export_jsonl(db)
            storage.export_entities(db, args.type)
        finally:
            db.close()


def argument_parser():
    parser = argparse.ArgumentParser(description="Thu thập thông tin và bài công khai của cá nhân/Trang/nhóm Facebook.")
    parser.add_argument("urls", nargs="+", metavar="URL")
    parser.add_argument("--type", choices=("profile", "page", "group"), required=True)
    parser.add_argument("--info-only", action="store_true")
    parser.add_argument("--max-posts", type=int, default=20)
    parser.add_argument("--comments", dest="max_comments", type=int, default=0,
                        help="số bình luận nổi bật cần lấy cho mỗi bài")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    return parser


def run_cli(argv=None):
    parser = argument_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(main(args))
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"LỖI: {exc}\n")
