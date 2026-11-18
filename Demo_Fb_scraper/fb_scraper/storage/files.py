"""Xuất snapshot qua file tạm và xử lý khóa file trên Windows."""
import json
import os
import tempfile
import time
from pathlib import Path

from fb_scraper.storage.sql import row_to_dict


# Xuất bảng ra JSONL; dùng chung cơ chế xử lý khóa file cho bài viết, trang cá nhân và nhóm.
def export_rows(db, target, query, json_fields=(), transform=None):
    """Đọc từng dòng SQLite và ghi JSONL qua cơ chế xuất file an toàn."""
    def write_rows(output):
        # Đây là hàm được atomic_write gọi sau khi đã mở file tạm.
        cursor = db.execute(query)
        for row in cursor:
            record = row_to_dict(cursor, row)
            for field in json_fields:
                if record.get(field) is not None:
                    record[field] = json.loads(record[field])
                else:
                    record[field] = None
            if transform is not None:
                record = transform(record)
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

    return atomic_write(target, write_rows)


def atomic_write(target, writer):
    """Ghi file tạm xong mới thay file đích, tránh để lại một file đích viết dở.

    writer là một hàm nhận file đang mở và ghi nội dung vào file đó.
    Nếu Windows khóa file đích, giữ bản mới ở file pending để người dùng khôi phục.
    """
    temporary_path = None
    writing_completed = False
    retry_delays = [0.1, 0.2, 0.4, 0.4, 0.4]

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_prefix = f".{target.stem}-"
        temporary_suffix = target.suffix + ".tmp"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=temporary_prefix,
            suffix=temporary_suffix,
            dir=target.parent,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            writer(output)

        writing_completed = True
        pending_path = target.with_name(f"{target.stem}.pending{target.suffix}")

        for attempt in range(6):
            try:
                temporary_path.replace(target)

                try:
                    pending_path.unlink(missing_ok=True)
                except OSError:
                    # File đích đã cập nhật; việc xóa bản pending cũ có thể thử lại sau.
                    pass

                return True
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(retry_delays[attempt])

    except OSError as error:
        if writing_completed:
            pending_path = target.with_name(f"{target.stem}.pending{target.suffix}")
            try:
                temporary_path.replace(pending_path)
            except OSError:
                # Nếu cả pending bị khóa, vẫn giữ nguyên file tạm đã viết xong.
                pending_path = temporary_path

            print(f"  Chưa cập nhật được {target.name} ({type(error).__name__}).", flush=True)
            print(f"  Bản xuất mới được giữ tại: {pending_path}", flush=True)
        else:
            print(
                f"  Chưa xuất được {target.name} ({type(error).__name__}); "
                "dữ liệu thu thập vẫn nằm trong SQLite.",
                flush=True,
            )

        return False
    finally:
        if temporary_path is not None and not writing_completed:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
