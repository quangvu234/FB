"""Chọn nội dung đầy đủ và đọc tên từ nhãn Facebook khi DOM không có link tên."""
import re

COMMENT_AUTHOR_SOURCE = (
    r"^\s*(?:Comment (?:by|from)|Reply by|Bình luận (?:của|dưới tên|bởi)|"
    r"Trả lời (?:của|dưới tên|bởi))\s+(.+?)(?:\s+(?:vào|lúc|at|on|cách đây)\s+.+)?$"
)
COMMENT_AUTHOR_RE = re.compile(COMMENT_AUTHOR_SOURCE, re.I)
EXPAND_LABEL_SOURCE = r"^\s*(?:Xem thêm|See more)\s*[.…]*\s*$"
EXPAND_LABEL_RE = re.compile(EXPAND_LABEL_SOURCE, re.I)
COLLAPSED_TEXT_RE = re.compile(r"(?:Xem thêm|See more)\s*[.…]*\s*$", re.I)


def comment_author(label):
    match = COMMENT_AUTHOR_RE.match(label or "")
    return match.group(1).strip() if match else None


def is_collapsed_text(text):
    return bool(COLLAPSED_TEXT_RE.search(text or ""))


def fuller_text(previous, incoming):
    """Không để bản rút gọn ghi đè bản đầy đủ; chấp nhận bản đã mở dù ngắn hơn nhãn UI."""
    previous, incoming = previous or "", incoming or ""
    if not incoming:
        return previous
    if is_collapsed_text(previous) != is_collapsed_text(incoming):
        return incoming if is_collapsed_text(previous) else previous
    old, new = previous.rstrip(), incoming.rstrip()
    if len(new) < len(old) and (old.startswith(new) or new.endswith(("…", "..."))):
        return previous
    return incoming
