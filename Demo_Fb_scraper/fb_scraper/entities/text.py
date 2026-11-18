"""Các hàm xử lý dòng văn bản và định danh cá nhân/nhóm."""
import re
from urllib.parse import parse_qs, urlparse

UI_LINES = {
    "xem thêm", "see more", "theo dõi", "follow", "tìm kiếm", "search", "chia sẻ", "share",
    "thêm bạn bè", "add friend", "nhắn tin", "message", "tham gia nhóm", "join group", "·",
}
SECTION_LABELS = {
    "thông tin cá nhân", "personal details", "cộng đồng", "community", "công việc", "work",
    "giáo dục", "education", "học vấn", "trình độ học vấn", "bài viết", "posts", "giới thiệu", "about",
    "tiểu sử", "bio", "intro", "reels", "ảnh", "photos", "bạn bè", "friends", "videos", "video",
    "giới thiệu về nhóm này", "about this group", "công khai", "public", "riêng tư", "private",
    "hiển thị", "visible", "ẩn", "hidden", "lịch sử", "history", "thành viên", "members",
    "hoạt động", "activity", "quy tắc nhóm", "group rules", "quy tắc", "rules",
    "thảo luận", "discussion", "sự kiện", "events", "file phương tiện", "media", "file", "files",
    "hạng mục", "categories", "category", "thông tin pháp lý và quyền riêng tư", "privacy and legal info",
    "đại học", "college", "university", "trường trung học", "high school",
}


# Chuẩn hóa khoảng trắng Facebook (kể cả NBSP) thành những dòng không rỗng.
def text_lines(text):
    """Tách văn bản thành dòng; bỏ dòng trống và gộp khoảng trắng thừa."""
    if not text:
        text = ""

    cleaned_lines = []
    for line in text.splitlines():
        if not line.strip():
            continue

        cleaned_line = re.sub(r"\s+", " ", line)
        cleaned_lines.append(cleaned_line.strip())

    return cleaned_lines


# Lấy nội dung nằm sau tiêu đề đã biết; dừng ở tiêu đề kế tiếp để tránh lẫn trường khác.
def section_lines(lines, labels, headings=()):
    """Lấy các dòng sau một tiêu đề, dừng trước tiêu đề kế tiếp."""
    accepted_labels = set()
    for label in labels:
        accepted_labels.add(label.casefold())

    stop_labels = set(SECTION_LABELS)

    # Một số tiêu đề có đuôi, ví dụ "Công việc · 2 mục".
    for heading in headings:
        for heading_line in text_lines(heading):
            normalized_heading = heading_line.casefold()
            for section_label in SECTION_LABELS:
                if normalized_heading.startswith(section_label + " ·"):
                    stop_labels.add(normalized_heading)
                    break

    for index in range(len(lines)):
        current_line = lines[index]
        if current_line.casefold() not in accepted_labels:
            continue

        result = []
        following_lines = lines[index + 1:]

        for value in following_lines:
            normalized_value = value.casefold()
            if normalized_value in stop_labels:
                break
            if normalized_value.startswith(("xem thêm ", "see more ")):
                break
            if normalized_value not in UI_LINES:
                result.append(value)

        if result:
            return result

    return None


# Dùng ID số khi URL chứa ID; username/slug được lưu như khóa khác, không giả thành Facebook ID.
def entity_identity(url):
    """Trả (khóa lưu trữ, ID số Facebook). Username không được giả thành ID số."""
    parsed_url = urlparse(url)
    query_parameters = parse_qs(parsed_url.query)
    token = query_parameters.get("id", [""])[0]

    if not token:
        token = parsed_url.path.rstrip("/").split("/")[-1]

    if token.isdigit():
        return token, token

    storage_id = "u_" + token.lower()
    numeric_id = None
    return storage_id, numeric_id


# Nhận diện trang lỗi trước khi lấy tên; giới hạn văn bản ở khu vực giới thiệu của profile.
def prepare_snapshot(raw, kind):
    lines = text_lines(raw.get("text", ""))
    if kind == "profile" and not raw.get("about_page"):
        for index, line in enumerate(lines):
            if line.casefold() in {"bài viết", "posts"}:
                lines = lines[:index]
                break
    return lines
