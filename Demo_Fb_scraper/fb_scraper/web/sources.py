"""Kiểm tra đầu vào và phân loại nguồn của giao diện."""
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from fb_scraper.common.urls import canonical_entity_url, FACEBOOK_HOSTS


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sources: str = Field(min_length=1, max_length=16000)
    mode: Literal["auto", "keyword", "profile", "page", "group"] = "auto"
    max_posts: int = Field(default=20, ge=1, le=500)
    max_comments: int = Field(default=10, ge=0, le=5000)
    ocr: bool = False


def build_plan(request):
    plan, seen = [], set()
    lines = [line.strip() for line in request.sources.splitlines() if line.strip()]
    if len(lines) > 50:
        raise ValueError("Mỗi lượt nhận tối đa 50 nguồn. Hãy chia thành nhiều lượt.")
    for line in lines:
        mode = request.mode
        candidate = line
        if line.lower().startswith(tuple(host + "/" for host in FACEBOOK_HOSTS)):
            candidate = "https://" + line
        parsed = urlparse(candidate)
        is_url = parsed.scheme in {"http", "https"} or "://" in candidate
        if mode == "auto":
            mode = "keyword"
            if is_url:
                if parsed.hostname not in FACEBOOK_HOSTS:
                    raise ValueError(f"URL phải thuộc Facebook: {line}")
                mode = "group" if parsed.path.startswith("/groups/") else "profile"
        kind = "profile" if mode == "page" else mode
        value = line
        if kind != "keyword":
            value = canonical_entity_url(candidate, kind)
            if not value:
                raise ValueError(f"URL {mode} không hợp lệ: {line}")
        elif is_url:
            raise ValueError("Đang chọn Từ khóa nhưng đầu vào là URL. Hãy chọn Tự nhận diện hoặc loại URL.")
        key = (kind, value)
        if key not in seen:
            seen.add(key)
            plan.append({"kind": kind, "mode": mode, "value": value})
    if not plan:
        raise ValueError("Hãy nhập ít nhất một từ khóa hoặc URL Facebook.")
    return plan
