"""Nhãn aria-label của bình luận, dùng chung cho Python và JavaScript."""
import re

# Cú pháp này hợp lệ ở cả Python và JavaScript: (?:...) là nhóm không ghi nhớ.
COMMENT_LABEL_SOURCE = (
    r"(?:Comment (?:by|from)|Reply by|Bình luận (?:của|dưới tên|bởi)|Trả lời (?:của|dưới tên))"
)

COMMENT_LABEL_RE = re.compile(r"^\s*" + COMMENT_LABEL_SOURCE + r"\b", re.I)

# Biểu thức chính quy dạng JavaScript, chèn vào các đoạn script chạy trong Chrome.
COMMENT_LABEL_JS = "/^" + COMMENT_LABEL_SOURCE + "/i"
