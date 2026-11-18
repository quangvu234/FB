"""Tiến trình riêng cho lượt thu thập; hủy tác vụ vẫn đi qua finally để xuất dữ liệu."""
import asyncio
import json
import sys
import threading

from fb_scraper.common.runtime import load_env, setup_console

EVENT_PREFIX = "@@SCRAPER_EVENT "


def emit(**event):
    print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False), flush=True)


def watch_stop(loop, task):
    for line in sys.stdin:
        if line.strip() == "stop":
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
            return


async def collect(config):
    from fb_scraper.browser.connection import browser_context
    from fb_scraper.common.models import CollectionOptions
    from fb_scraper.entities.collector import collect_entities
    from fb_scraper.posts.collector import build_sources
    from fb_scraper.posts.pipeline import collect_source_posts
    from fb_scraper.storage import database as storage

    options = CollectionOptions.model_validate(config["options"])
    plan = config["plan"]
    task = asyncio.current_task()
    threading.Thread(target=watch_stop, args=(asyncio.get_running_loop(), task), daemon=True).start()
    db = storage.init_db()
    cancelled = False
    try:
        ocr = None
        if options.ocr and any(source["kind"] == "keyword" for source in plan):
            from fb_scraper.common.ocr import OCREngine
            ocr = await asyncio.to_thread(OCREngine)
        known = storage.known_ids(db)
        async with browser_context() as context:
            for index, source in enumerate(plan):
                emit(type="source", current=index + 1, completed=index, total=len(plan), label=source["value"])
                print(f"Bắt đầu nguồn {index + 1}/{len(plan)}: {source['value']}", flush=True)
                if source["kind"] == "keyword":
                    page = await context.new_page()
                    try:
                        await collect_source_posts(page, context, db, build_sources([source["value"]])[0],
                                                   options, known, ocr)
                    finally:
                        await page.close()
                else:
                    await collect_entities(context, [source["value"]], source["kind"], options, db=db,
                                           source_type="page" if source.get("mode") == "page" else None)
                    known = storage.known_ids(db)
                emit(type="source_done", completed=index + 1, total=len(plan))
    except asyncio.CancelledError:
        cancelled = True
        print("Đã nhận yêu cầu dừng. Đang lưu kết quả đã thu thập…", flush=True)
    finally:
        try:
            storage.export_jsonl(db)
            for kind in {source["kind"] for source in plan} & {"profile", "group"}:
                storage.export_entities(db, kind)
            print(f"Đã lưu dữ liệu. Database hiện có {storage.count_rows(db, 'posts')} bài viết.", flush=True)
        finally:
            db.close()
    return 130 if cancelled else 0


def main():
    setup_console()
    load_env()
    config = json.loads(sys.stdin.readline())
    try:
        if config.get("action") == "browser":
            from fb_scraper.browser.launcher import open_chrome
            open_chrome()
            return 0
        return asyncio.run(collect(config))
    except Exception as error:
        print(f"LỖI: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
