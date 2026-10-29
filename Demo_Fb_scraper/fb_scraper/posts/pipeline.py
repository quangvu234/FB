"""Lưu bài trước, rồi bổ sung bình luận, ảnh và OCR."""
import asyncio

from playwright.async_api import BrowserContext

from fb_scraper.posts.comments import scrape_top_comments
from fb_scraper.posts.reader import iter_source_posts
from fb_scraper.storage.database import IMG_DIR, known_ids, load_post, save_post


# Tải tối đa limit ảnh vào data/images; trả danh sách đường dẫn các ảnh tải thành công.
async def download_images(ctx: BrowserContext, post: dict, limit=4):
    """Tải tối đa limit ảnh; một ảnh lỗi không ngăn việc tải những ảnh còn lại."""
    downloaded_files = []
    selected_images = post["images"][:limit]

    for index, image_url in enumerate(selected_images):
        try:
            response = await ctx.request.get(image_url, timeout=15000)
            if response.ok:
                image_path = IMG_DIR / f"{post['post_id']}_{index}.jpg"
                image_bytes = await response.body()
                image_path.write_bytes(image_bytes)
                downloaded_files.append(str(image_path))
            else:
                print(f"  Không tải được ảnh {index}: HTTP {response.status}")
        except Exception as error:
            print(f"  Không tải được ảnh {index}: {type(error).__name__}")

    return downloaded_files


# Thu thập và lưu bài của một nguồn; các crawler khác có thể dùng lại hàm này.
# post_fields bổ sung thông tin liên kết nguồn mà không thay đổi nội dung bài đã lưu.
async def collect_source_posts(page, ctx, db, src, args, done=None, ocr=None, post_fields=None):
    """Lưu nội dung trước, sau đó mới bổ sung bình luận, ảnh và OCR."""
    if done is None:
        done = known_ids(db)

    saved_count = 0
    skipped_count = 0
    updated_count = 0

    async for post in iter_source_posts(page, src, args.max_posts):
        if post_fields:
            post.update(post_fields)

        post_id = post["post_id"]
        if post_id in done:
            previous_post = load_post(db, post_id)
            source_changed = False

            if post_fields:
                for field, value in post_fields.items():
                    if previous_post.get(field) != value:
                        source_changed = True
                        break

            if source_changed:
                previous_post.update(post_fields)
                save_post(db, previous_post)

            old_comments = previous_post["top_comments"]
            if args.comments > len(old_comments):
                print(f"  Bổ sung bình luận cho bài đã có: {post_id}", flush=True)
                comment_url = post["url"]
                if not comment_url:
                    comment_url = previous_post["url"]

                new_comments = await scrape_top_comments(ctx, comment_url, args.comments)
                if new_comments:
                    merged_comments = []
                    seen_comments = set()

                    for comment in new_comments + old_comments:
                        if comment not in seen_comments:
                            seen_comments.add(comment)
                            merged_comments.append(comment)

                    previous_post["top_comments"] = merged_comments[:args.comments]
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
        done.add(post_id)
        saved_count += 1
        print(f"  Đã lưu {post_id} vào SQLite", flush=True)

        try:
            comments = await scrape_top_comments(ctx, post["url"], args.comments)
            post["top_comments"] = comments

            if comments:
                save_post(db, post)
            if args.comments:
                print(f"  Đã lưu {len(comments)} bình luận cho {post_id}", flush=True)

            image_files = await download_images(ctx, post)
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
