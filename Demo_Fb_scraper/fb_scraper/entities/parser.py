"""Ghép dữ liệu DOM thành bản ghi profile hoặc nhóm; không làm I/O."""
import re

from fb_scraper.entities.text import (
    NUMBER, SECTION_LABELS, UI_LINES, entity_identity,
    parse_display_count, prepare_snapshot, section_lines, text_lines,
)
from fb_scraper.common.urls import canonical_entity_url, entity_about_url
from fb_scraper.common.models import ENTITY_MODELS


# Ghép trang chính và trang Giới thiệu thành bản ghi chỉ gồm các trường đã chọn.
def parse_entity(url, kind, snapshots, source_url=None, partial=False):
    """Ghép các lần đọc trang thành một bản ghi thông tin cá nhân hoặc nhóm."""
    base_url = canonical_entity_url(url, kind)
    if not base_url:
        raise ValueError(f"URL {kind} không hợp lệ: {url}")

    storage_id, numeric_id = entity_identity(base_url)

    if not source_url:
        source_url = url

    collection_status = "ok"
    if partial:
        collection_status = "partial"

    record = {
        "entity_id": storage_id,
        f"{kind}_id": numeric_id,
        "url": base_url,
        "source_url": source_url,
        "about_url": entity_about_url(base_url, kind),
        "name": None,
        "collection_status": collection_status,
    }

    if kind == "profile":
        fields = (
            "account_type", "bio", "followers_count", "followers_raw",
            "work", "education", "current_city", "hometown",
        )
    else:
        fields = ("description", "privacy", "members_count", "members_raw", "rules")

    for field in fields:
        record[field] = None

    # Mỗi phần tử lưu cả dữ liệu DOM gốc lẫn các dòng văn bản đã làm sạch.
    readable_pages = []
    login_was_required = False

    for snapshot in snapshots:
        if snapshot.get("login_required"):
            login_was_required = True
        if snapshot.get("unavailable") or snapshot.get("login_required"):
            continue

        page_data = {
            "snapshot": snapshot,
            "lines": prepare_snapshot(snapshot, kind),
        }
        readable_pages.append(page_data)

    if not readable_pages:
        if login_was_required:
            record["collection_status"] = "login_required"
        else:
            record["collection_status"] = "unavailable"

        model_class = ENTITY_MODELS[kind]
        validated_record = model_class.model_validate(record)
        return validated_record.model_dump(exclude={"collected_at"})

    # Tìm tên trên trang đọc được đầu tiên; tránh nhận nhầm tên nút giao diện.
    for page_data in readable_pages:
        snapshot = page_data["snapshot"]
        lines = page_data["lines"]
        name = " ".join(text_lines(snapshot.get("name", "")))

        if not name:
            if lines:
                name = lines[0]
            else:
                name = None

        if not name:
            continue

        normalized_name = name.casefold()
        if normalized_name in UI_LINES:
            continue
        if normalized_name in SECTION_LABELS or normalized_name == "facebook":
            continue

        record["name"] = name
        break

    if not record["name"]:
        record["collection_status"] = "partial"
    if len(readable_pages) < len(snapshots):
        record["collection_status"] = "partial"

    if kind == "profile":
        _read_profile_fields(record, readable_pages)
    else:
        _read_group_fields(record, readable_pages)

    model_class = ENTITY_MODELS[kind]
    validated_record = model_class.model_validate(record)
    return validated_record.model_dump(exclude={"collected_at"})


def _read_profile_fields(record, readable_pages):
    """Điền thông tin profile vào record; mỗi nhóm trường có một bước riêng."""
    field_labels = {
        "bio": ("tiểu sử", "bio", "intro"),
        "work": ("công việc", "work"),
        "education": ("giáo dục", "education", "học vấn", "trình độ học vấn"),
    }
    education_labels = (
        ("đại học", "college", "university"),
        ("trường trung học", "high school"),
    )
    location_patterns = {
        "current_city": r"^(?:Sống ở|Lives in)\s+(.+)$",
        "hometown": r"^(?:Từ|From)\s+(.+)$",
    }

    for page_data in readable_pages:
        snapshot = page_data["snapshot"]
        lines = page_data["lines"]
        headings = snapshot.get("headings", ())
        page_text = "\n".join(lines)

        follower_match = re.search(NUMBER + r"\s*(?:người theo dõi|followers?)\b", page_text, re.I)
        if not follower_match:
            follower_match = re.search(r"(?:Followed by)\s*" + NUMBER + r"\s*(?:people)?", page_text, re.I)

        if follower_match:
            record["followers_count"] = parse_display_count(follower_match.group(1))
            record["followers_raw"] = follower_match.group(0).strip()

        for field, labels in field_labels.items():
            values = section_lines(lines, labels, headings)
            if not values:
                continue

            if field == "bio":
                record[field] = "\n".join(values)
            else:
                record[field] = values

        education = []
        for labels in education_labels:
            values = section_lines(lines, labels, headings)
            if values:
                education.extend(values)

        if education:
            record["education"] = education

        for field, pattern in location_patterns.items():
            for line in lines:
                location_match = re.match(pattern, line, re.I)
                if location_match:
                    record[field] = location_match.group(1).strip()
                    break

        found_page_label = False
        found_profile_label = False

        for line in lines:
            if re.match(r"^(?:Trang|Page)\s*[·•]", line, re.I):
                found_page_label = True
            if re.fullmatch(r"(?:Trang cá nhân|Profile)(?:\s*[·•].*)?", line, re.I):
                found_profile_label = True

        if found_page_label:
            record["account_type"] = "page"
        elif found_profile_label:
            record["account_type"] = "profile"


def _read_group_fields(record, readable_pages):
    """Điền thông tin nhóm; ưu tiên số thành viên đầy đủ hơn số rút gọn."""
    best_member_count = None

    for page_data in readable_pages:
        snapshot = page_data["snapshot"]
        lines = page_data["lines"]
        headings = snapshot.get("headings", ())

        for line in lines:
            if record["privacy"] is None:
                if re.fullmatch(r"(?:Nhóm )?Công khai|Public(?: group)?", line, re.I):
                    record["privacy"] = "public"
                elif re.fullmatch(r"(?:Nhóm )?Riêng tư|Private(?: group)?", line, re.I):
                    record["privacy"] = "private"

            member_match = re.search(NUMBER + r"\s*(?:thành viên|members?)\b", line, re.I)
            if not member_match:
                continue

            count_text = member_match.group(1)
            count = parse_display_count(count_text)
            is_exact = not re.search(r"[a-zA-Zà-ỹ]", count_text)

            candidate = {
                "is_exact": is_exact,
                "count": count,
                "raw": line,
            }

            if best_member_count is None:
                best_member_count = candidate
                continue

            # Ví dụ 56.060 được ưu tiên hơn 56,1K, kể cả khi số ước lượng lớn hơn.
            if is_exact and not best_member_count["is_exact"]:
                best_member_count = candidate
                continue

            if is_exact == best_member_count["is_exact"]:
                comparable_count = count
                if not comparable_count:
                    comparable_count = 0

                best_count = best_member_count["count"]
                if not best_count:
                    best_count = 0

                if comparable_count > best_count:
                    best_member_count = candidate

        description = section_lines(lines, ("giới thiệu về nhóm này", "about this group"), headings)
        rules = section_lines(lines, ("quy tắc nhóm", "group rules", "quy tắc", "rules"), headings)

        if description:
            record["description"] = "\n".join(description)
        if rules:
            record["rules"] = rules

    if best_member_count is not None:
        record["members_count"] = best_member_count["count"]
        record["members_raw"] = best_member_count["raw"]
