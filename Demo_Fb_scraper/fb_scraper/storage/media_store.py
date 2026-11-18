"""Media thuộc đúng một bài hoặc bình luận, giữ thứ tự, hash và kết quả OCR."""
import hashlib
import json
from pathlib import Path

from fb_scraper.storage.schema import as_dict, json_text


def file_hash(path):
    if not path:
        return None
    try:
        if not Path(path).is_file():
            return None
        with Path(path).open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except OSError:
        return None


def media_rows(db, *, post_id=None, comment_id=None):
    field, identity = ("post_id", post_id) if post_id is not None else ("comment_id", comment_id)
    cursor = db.execute(f"SELECT * FROM media WHERE {field}=? ORDER BY position,id", (identity,))
    records = [as_dict(cursor, row) for row in cursor]
    for record in records:
        record["metadata"] = json.loads(record["metadata"] or "{}")
    return records


def write_media(db, items, *, post_id=None, comment_id=None):
    if (post_id is None) == (comment_id is None):
        raise ValueError("Media phải thuộc đúng một post_id hoặc comment_id.")
    field, owner = ("post_id", post_id) if post_id is not None else ("comment_id", comment_id)
    for index, item in enumerate(items):
        kind = item.get("media_type", "image")
        if kind not in {"image", "video", "gif"}:
            raise ValueError("media_type phải là image, video hoặc gif.")
        position = item.get("position", index)
        if not isinstance(position, int) or position < 0:
            raise ValueError("position phải là số nguyên không âm.")
        url, path = item.get("media_url") or None, item.get("file_path") or None
        candidates = media_rows(db, **{field: owner})
        previous = next((record for record in candidates if
                         (url and record["media_url"] == url) or (path and record["file_path"] == path) or
                         (not url and not path and record["position"] == position and record["media_type"] == kind)), {})
        # URL có chữ ký có thể đổi trong khi file đã tải vẫn là cùng một đường dẫn.
        # Gộp dòng URL tạm vào dòng file trước khi UPDATE để không vi phạm UNIQUE.
        for duplicate in candidates:
            if previous and duplicate["id"] != previous["id"] and (
                (url and duplicate["media_url"] == url) or (path and duplicate["file_path"] == path)
            ):
                for name in ("file_path", "file_hash", "ocr_text"):
                    if not previous.get(name):
                        previous[name] = duplicate.get(name)
                previous["metadata"] = {**duplicate["metadata"], **previous["metadata"]}
                db.execute("DELETE FROM media WHERE id=?", (duplicate["id"],))
        metadata = {**previous.get("metadata", {}), **item.get("metadata", {})}
        values = {"post_id": post_id, "comment_id": comment_id, "media_type": kind,
                  "media_url": url or previous.get("media_url"), "file_path": path or previous.get("file_path"),
                  "file_hash": item.get("file_hash") or previous.get("file_hash") or file_hash(path),
                  "ocr_text": item.get("ocr_text") if item.get("ocr_text") is not None else previous.get("ocr_text"),
                  "position": position, "metadata": json_text(metadata)}
        if previous:
            db.execute(f"UPDATE media SET {','.join(key+'=?' for key in values)} WHERE id=?",
                       (*values.values(), previous["id"]))
        else:
            db.execute(f"INSERT INTO media({','.join(values)}) VALUES({','.join('?' for _ in values)})", tuple(values.values()))


def post_media_input(record):
    items = [dict(item) for item in record.get("media", [])]
    images = record.get("images", [])
    files = record.get("image_files", [])
    ocr = record.get("ocr", [])
    for index, url in enumerate(images):
        kind = "gif" if url.lower().split("?", 1)[0].endswith(".gif") else "image"
        items.append({"media_type": kind, "media_url": url, "position": index})
    for index, path in enumerate(files):
        position = index
        prefix, _, suffix = Path(path).stem.rpartition("_")
        if prefix == record.get("post_id") and suffix.isdigit():
            position = int(suffix)
        item = {"media_type": "image", "file_path": path, "position": position}
        if position < len(images):
            item["media_url"] = images[position]
            item["media_type"] = "gif" if images[position].lower().split("?", 1)[0].endswith(".gif") else "image"
        if index < len(ocr):
            item.update(ocr_text=ocr[index].get("text", ""), metadata={"ocr": ocr[index]})
        items.append(item)
    # OCR có thể được cập nhật riêng mà không truyền lại danh sách ảnh.
    if not files:
        for index, result in enumerate(ocr):
            item = {"media_type": "image", "position": index, "ocr_text": result.get("text", ""), "metadata": {"ocr": result}}
            if index < len(images):
                item["media_url"] = images[index]
            items.append(item)
    return items
