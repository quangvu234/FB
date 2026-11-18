"""Lưu bài trước, rồi bổ sung bình luận, ảnh và OCR."""
import asyncio
import hashlib

from playwright.async_api import BrowserContext

from fb_scraper.common.comments import merge_comment_records, needs_comment_refresh
from fb_scraper.common.content import fuller_text
from fb_scraper.posts.comments import scrape_top_comments
from fb_scraper.posts.reader import iter_source_posts
from fb_scraper.storage.database import IMG_DIR, known_ids, load_post, save_post


# Tải tối đa limit ảnh vào data/images; trả danh sách đường dẫn các ảnh tải thành công.
async def download_images(context: BrowserContext, post: dict, limit=4):
    """Tải tối đa limit ảnh; một ảnh lỗi không ngăn việc tải những ảnh còn lại."""
    downloaded_files = []
    selected_images = post["images"][:limit]

    for index, image_url in enumerate(selected_images):
        try:
            response = await context.request.get(image_url, timeout=15000)
            if response.ok:
                image_path = IMG_DIR / f"{post['post_id']}_{index}.jpg"
                image_bytes = await response.body()
                image_path.write_bytes(image_bytes)
                downloaded_files.append(str(image_path))
                post.setdefault("media", []).append({
                    "media_type": "gif" if image_url.lower().split("?", 1)[0].endswith(".gif") else "image",
                    "media_url": image_url, "file_path": str(image_path), "position": index,
                    "file_hash": hashlib.sha256(image_bytes).hexdigest(),
                })
            else:
                print(f"  Không tải được ảnh {index}: HTTP {response.status}")
        except Exception as error:
            print(f"  Không tải được ảnh {index}: {type(error).__name__}")

    return downloaded_files


async def collect_source_posts(page, context, db, source, options, known_post_ids=None, ocr=None, post_fields=None):
    """Thu thập và lưu bài của một nguồn; lưu nội dung trước, sau đó mới bổ sung bình luận, ảnh và OCR.

    options: CollectionOptions (max_posts, max_comments).
    known_post_ids: tập post_id đã có trong SQLite, được cập nhật khi lưu bài mới.
    post_fields: trường liên kết nguồn (entity_type, entity_id) gắn thêm vào bài.
    """
    if known_post_ids is None:
        known_post_ids = known_ids(db)

    saved_count = 0
    skipped_count = 0
    updated_count = 0

    async for post in iter_source_posts(page, source, options.max_posts):
        if post_fields:
            post.update(post_fields)

        post_id = post["post_id"]
        if post_id in known_post_ids:
            previous_post = load_post(db, post_id)
            source_changed = False
            # Đọc lại phải cập nhật tên và nội dung, kể cả bài đã có đủ bình luận.
            full_text = fuller_text(previous_post.get("text"), post.get("text"))
            if full_text != previous_post.get("text", ""):
                previous_post["text"] = full_text
                source_changed = True
            if post.get("author") and post["author"] != previous_post.get("author"):
                previous_post["author"] = post["author"]
                source_changed = True
            if post.get("url") and not previous_post.get("url"):
                previous_post["url"] = post["url"]
                source_changed = True

            if post_fields:
                for field, value in post_fields.items():
                    if previous_post.get(field) != value:
                        source_changed = True
                        break

            if source_changed:
                previous_post.update(post_fields or {})
            for field in ("likes", "comments", "shares", "posted_at", "posted_raw"):
                if post.get(field) not in (None, ""):
                    previous_post[field] = post[field]
            # last_seen_at/last_checked_at phải đổi cả khi bài và bình luận đã đầy đủ.
            excluded = {"top_comments", "media", "images", "image_files", "ocr", "source_record", "comment_records"}
            save_post(db, {field: value for field, value in previous_post.items() if field not in excluded})

            old_comments = previous_post["top_comments"]
            if needs_comment_refresh(old_comments, options.max_comments):
                print(f"  Bổ sung bình luận cho bài đã có: {post_id}", flush=True)
                comment_url = post["url"]
                if not comment_url:
                    comment_url = previous_post["url"]

                new_comments = await scrape_top_comments(context, comment_url, options.max_comments)
                if new_comments:
                    # Giữ các bản ghi cũ và quan hệ đã biết khi DOM chỉ tải một phần.
                    previous_post["top_comments"] = merge_comment_records(old_comments, new_comments)
                    if post["url"]:
                        previous_post["url"] = post["url"]

                    save_post(db, previous_post)
                    updated_count += 1
                    comment_count = len(previous_post["top_comments"])
                    print(f"  Đã lưu {comment_count} bình luận vào SQLite", flush=True)

            skipped_count += 1
            continue

        # SQLite commit ngay: lỗi tải ảnh/OCR hoặc Ctrl+C về sau vẫn giữ nội dung này.
        save_post(db, post)
        known_post_ids.add(post_id)
        saved_count += 1
        print(f"  Đã lưu {post_id} vào SQLite", flush=True)

        try:
            comments = await scrape_top_comments(context, post["url"], options.max_comments)
            post["top_comments"] = comments

            if comments:
                save_post(db, post)
            if options.max_comments:
                print(f"  Đã lưu {len(comments)} bình luận cho {post_id}", flush=True)

            image_files = await download_images(context, post)
            post["image_files"] = image_files

            if ocr and image_files:
                ocr_results = []
                for image_file in image_files:
                    result = await asyncio.to_thread(ocr.read, image_file)
                    ocr_results.append(result)
                post["ocr"] = ocr_results

        except Exception as error:
            print(f"  Bỏ qua bước bổ sung bị lỗi ({type(error).__name__}); nội dung bài đã lưu.")

        if post.get("image_files") or post.get("ocr"):
            save_post(db, post)

    print(
        f"  Đã lưu mới: {saved_count}; bài đã có: {skipped_count}; "
        f"bài bổ sung bình luận: {updated_count}",
        flush=True,
    )
