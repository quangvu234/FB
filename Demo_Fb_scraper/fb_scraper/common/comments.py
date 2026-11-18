"""Bình luận có cấu trúc; giữ tương thích với danh sách chuỗi của bản cũ."""
import base64
import binascii
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from fb_scraper.common.content import fuller_text, is_collapsed_text


def canonical_comment_id(value):
    """DOM dùng cả ID số và global ID base64 `comment:<post>_<comment>`."""
    value = str(value)
    try:
        decoded = base64.b64decode(value, validate=True).decode("ascii")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return value
    match = re.fullmatch(r"comment:\d+_(\d+)", decoded)
    return match.group(1) if match else value


class Comment(BaseModel):
    comment_id: str | None = None
    parent_comment_id: str | None = None
    root_comment_id: str | None = None
    is_reply: bool | None = None
    author: str | None = None
    author_url: str | None = None
    text: str = ""
    url: str | None = None
    posted_raw: str | None = None
    created_at: str | None = None
    reaction_count: int | None = Field(default=None, ge=0)
    media: list[dict] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_text(cls, value):
        # Chuỗi cũ không chứa bằng chứng đáng tin về ID hay quan hệ cha-con.
        if isinstance(value, str):
            return {"text": value}
        return value

    @field_validator("comment_id", "parent_comment_id", "root_comment_id", mode="before")
    @classmethod
    def normalize_id(cls, value):
        if value is None or value == "":
            return None
        return canonical_comment_id(value)

    @model_validator(mode="after")
    def check_relationship(self):
        if self.parent_comment_id is not None:
            if self.parent_comment_id == self.comment_id:
                raise ValueError("Bình luận không thể là cha của chính nó.")
            self.is_reply = True
        if self.is_reply is False:
            self.root_comment_id = self.comment_id
        return self


def normalize_comments(comments):
    return [Comment.model_validate(comment).model_dump() for comment in comments]


def comment_key(comment):
    """Ưu tiên Facebook ID; thiếu ID thì chỉ gộp các bản ghi có cùng ngữ cảnh."""
    if comment["comment_id"]:
        return ("id", comment["comment_id"])
    return ("text", comment["author"], comment["author_url"], comment["text"],
            comment["parent_comment_id"], comment["root_comment_id"], comment["is_reply"])


def merge_comment_records(*batches):
    """Cùng ID được cập nhật; nội dung giống nhau nhưng ID khác vẫn là hai bình luận."""
    merged = {}
    for batch in batches:
        for comment in normalize_comments(batch):
            key = comment_key(comment)
            previous = merged.get(key, {})
            updates = {field: value for field, value in comment.items() if value is not None and value != ""}
            updates["text"] = fuller_text(previous.get("text"), updates.get("text"))
            merged[key] = Comment.model_validate({**previous, **updates}).model_dump()
    return list(merged.values())


def needs_comment_refresh(comments, limit):
    if limit <= 0:
        return False
    return len(comments) < limit or any(
        not comment["comment_id"] or comment["is_reply"] is None or not comment["author"]
        or is_collapsed_text(comment["text"])
        for comment in normalize_comments(comments)
    )
