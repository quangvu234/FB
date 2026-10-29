"""Điều phối thu thập thông tin và bài viết cá nhân/nhóm qua CLI."""
import argparse
import asyncio
import sys

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
    if kind == "group" and entity["privacy"] != "public":
        print("  Chỉ thu thập bài viết của nhóm được xác định là Công khai.", flush=True)
        return None
    return {"url": entity["url"], "name": f"{kind}:{entity['entity_id']}", "public_only": kind == "profile"}


async def collect_entities(context, urls, kind, options=None, *, db=None):
    """Nhận context/DB có sẵn để search và entity dùng chung kết nối.

    db=None: hàm tự mở DB, xuất snapshot và đóng DB.
    db được truyền vào: bên gọi tiếp tục chịu trách nhiệm xuất/đóng DB đó.
    """
    sources = validate_sources(urls, kind)

    if not options:
        options = CollectionOptions()

    owns_database = db is None
    if owns_database:
        db = storage.init_db()

    page = None
    try:
        known_post_ids = set()
        if not options.info_only and options.max_posts:
            known_post_ids = storage.known_ids(db)

        ocr_engine = None
        if options.ocr and not options.info_only and options.max_posts:
            from fb_scraper.common.ocr import OCREngine
            ocr_engine = OCREngine(gpu=options.gpu)

        page = await context.new_page()

        for url in sources:
            print(f"==> {kind}:{url}", flush=True)

            try:
                entity = await scrape_entity(page, url, kind)
            except Exception as error:
                print(f"  Lỗi đọc thông tin ({type(error).__name__}): {error}", flush=True)
                continue

            storage.save_entity(db, kind, entity)
            displayed_name = entity["name"]
            if not displayed_name:
                displayed_name = entity["entity_id"]

            status = entity["collection_status"]
            print(f"  Đã lưu {displayed_name} vào SQLite; trạng thái: {status}", flush=True)

            if options.info_only or options.max_posts == 0:
                continue
            if not entity["name"] or status in {"login_required", "unavailable"}:
                print("  Bỏ qua bài viết: chưa truy cập được thông tin đối tượng.", flush=True)
                continue

            source = post_source(entity, kind)
            if source:
                entity_fields = {
                    "entity_type": kind,
                    "entity_id": entity["entity_id"],
                }
                await post_pipeline.collect_source_posts(
                    page, context, db, source, options, known_post_ids, ocr_engine,
                    post_fields=entity_fields,
                )
    finally:
        try:
            if page is not None:
                await page.close()
        finally:
            # Không đóng DB được search_collector truyền vào.
            if owns_database:
                try:
                    storage.export_jsonl(db)
                    storage.export_entities(db, kind)
                finally:
                    db.close()


async def main(args):
    command_options = vars(args)
    options = CollectionOptions.model_validate(command_options)
    sources = validate_sources(args.urls, args.type)
    async with browser_context() as context:
        await collect_entities(context, sources, args.type, options)


def argument_parser():
    parser = argparse.ArgumentParser(description="Thu thập thông tin và bài công khai của cá nhân/Trang/nhóm Facebook.")
    parser.add_argument("urls", nargs="+", metavar="URL")
    parser.add_argument("--type", choices=("profile", "group"), required=True)
    parser.add_argument("--info-only", action="store_true")
    parser.add_argument("--max-posts", type=int, default=20)
    parser.add_argument("--comments", type=int, default=0)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--gpu", action="store_true")
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
