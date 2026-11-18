"""Ghi toàn bộ bài/nguồn/bình luận/media trong một transaction của bên gọi."""
from fb_scraper.common.models import Post
from fb_scraper.common.content import fuller_text
from fb_scraper.storage.comment_store import write_comments
from fb_scraper.storage.media_store import write_media, post_media_input
from fb_scraper.storage.records import load_post
from fb_scraper.storage.source_store import source_for_post
from fb_scraper.storage.schema import json_text, now


def write_post(db, post):
    incoming = Post.model_validate(post).model_dump(exclude_unset=True)
    key = incoming.get("post_id")
    if not key:
        raise ValueError("Bài viết phải có post_id/post_key trước khi lưu.")
    previous = load_post(db, key) or {}
    merged = {**{field: value for field, value in previous.items() if value is not None}, **incoming}
    if "source_id" not in incoming and any(
        field in incoming and incoming[field] != previous.get(field)
        for field in ("source_ref", "source_type", "entity_type", "entity_id")
    ):
        merged["source_id"] = None
    record = Post.model_validate(merged).model_dump()
    for field in ("author", "author_url", "url", "posted_raw", "posted_at", "likes", "comments", "shares"):
        if record[field] in (None, "") and previous.get(field) not in (None, ""):
            record[field] = previous[field]
    source_id = source_for_post(db, record)
    metadata = {"source": record["source"], "links": record["links"],
                "entity_type": record["entity_type"], "entity_id": record["entity_id"]}
    # source_id đã lưu chỉ đổi khi caller thực sự cung cấp nguồn mới.
    values = {"source_id": source_id, "post_key": key,
              "content": fuller_text(previous.get("text"), record["text"]),
              "posted_at": record["posted_at"], "is_shared": int(record["is_shared"]),
              "original_post_key": record["original_post_key"],
              "collected_at": previous.get("collected_at") or record.get("collected_at") or now(),
              "last_seen_at": now(), "url": record["url"], "author": record["author"],
              "author_url": record["author_url"], "posted_raw": record["posted_raw"],
              "reaction_count": record["likes"], "comment_count": record["comments"],
              "share_count": record["shares"], "metadata": json_text(metadata)}
    columns = tuple(values)
    updates = ','.join(f'{field}=excluded.{field}' for field in columns if field not in {"post_key", "collected_at"})
    db.execute(f"INSERT INTO posts({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) "
               f"ON CONFLICT(post_key) DO UPDATE SET {updates}", tuple(values.values()))
    identity = db.execute("SELECT id FROM posts WHERE post_key=?", (key,)).fetchone()[0]
    if "top_comments" in incoming:
        if not incoming["top_comments"]:
            # Chỉ [] truyền tường minh mới xóa bình luận; các cập nhật bỏ trường này giữ nguyên.
            ids = [row[0] for row in db.execute("SELECT id FROM comments WHERE post_id=?", (identity,))]
            for comment_id in ids:
                db.execute("DELETE FROM media WHERE comment_id=?", (comment_id,))
            db.execute("UPDATE comments SET parent_comment_id=NULL WHERE post_id=?", (identity,))
            db.execute("DELETE FROM comments WHERE post_id=?", (identity,))
        else:
            write_comments(db, identity, key, incoming["top_comments"])
    if any(field in incoming for field in ("media", "images", "image_files", "ocr")):
        write_media(db, post_media_input(record), post_id=identity)
    return identity
