"""Phân biệt permalink bài Facebook với trang tìm kiếm/điều hướng."""
import hashlib
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com", "web.facebook.com"}
POST_PATH_RE = re.compile(r"/(?:posts|permalink|videos|reel)/(?:\d+|pfbid[a-zA-Z0-9]+)(?:/|$)")
PHOTO_PATH_RE = re.compile(r"/photos/(?:[^/]+/)*(?:\d+|pfbid[a-zA-Z0-9]+)(?:/|$)")
SHARE_PATH_RE = re.compile(r"^/share/[pvr]/[a-zA-Z0-9]+/?$")


def make_post_id(url: str, text: str) -> str:
    """Ưu tiên ID trong URL. Nếu không có ID, tạo khóa từ URL và 200 ký tự đầu."""
    id_pattern = r"(pfbid\w+)|/(?:posts|videos|reel)/(\d+)|(?:story_fbid|fbid|v)=(\d+)"
    match = re.search(id_pattern, url)

    if match:
        for matched_group in match.groups():
            if matched_group:
                return matched_group

    fingerprint_text = url + text[:200]
    fingerprint_bytes = fingerprint_text.encode()
    fingerprint = hashlib.md5(fingerprint_bytes).hexdigest()
    return "h_" + fingerprint[:16]


# Chuẩn hóa URL trang cá nhân/nhóm; loại trang tìm kiếm, permalink và URL ngoài Facebook.
def canonical_entity_url(href: str, kind: str) -> str:
    """Trả URL cá nhân/nhóm đã bỏ tracking; trả chuỗi rỗng nếu URL không phù hợp."""
    if kind not in {"profile", "group"} or not href:
        return ""

    try:
        absolute_url = urljoin("https://www.facebook.com/", href)
        parsed_url = urlparse(absolute_url)

        if parsed_url.scheme not in {"http", "https"}:
            return ""
        if parsed_url.hostname not in FACEBOOK_HOSTS:
            return ""
    except ValueError:
        return ""

    path_parts = []
    for part in parsed_url.path.split("/"):
        if part:
            path_parts.append(part)

    if kind == "group":
        if len(path_parts) not in {2, 3}:
            return ""
        if path_parts[0] != "groups":
            return ""

        if len(path_parts) == 3:
            if path_parts[2] not in {"about", "discussion", "rules"}:
                return ""

        group_name = path_parts[1]
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", group_name):
            return ""

        reserved_group_names = {"feed", "discover", "joins", "create", "search", "notifications"}
        if group_name.lower() in reserved_group_names:
            return ""

        return f"https://www.facebook.com/groups/{group_name}"

    # Dạng URL sử dụng ID số: profile.php?id=123.
    if path_parts == ["profile.php"]:
        query_parameters = parse_qs(parsed_url.query)
        profile_id = query_parameters.get("id", [""])[0]
        if profile_id.isdigit():
            return f"https://www.facebook.com/profile.php?id={profile_id}"
        return ""

    # Dạng /people/ten/123 hoặc /pages/ten/123, có thể có đuôi /about.
    if len(path_parts) in {3, 4}:
        route = path_parts[0]
        numeric_id = path_parts[2]

        if route in {"pages", "people"} and numeric_id.isdigit():
            if len(path_parts) == 3:
                return f"https://www.facebook.com/{route}/{path_parts[1]}/{numeric_id}"
            if path_parts[3] == "about":
                return f"https://www.facebook.com/{route}/{path_parts[1]}/{numeric_id}"

    reserved_routes = {
        "groups", "search", "posts", "permalink.php", "story.php", "photo", "photo.php",
        "watch", "videos", "reel", "reels", "stories", "share", "login", "checkpoint",
        "home.php", "profile.php", "pages", "people", "events", "marketplace", "gaming", "friends",
        "settings", "help", "notifications", "messages", "me", "about",
    }
    if not path_parts:
        return ""

    username = path_parts[0]
    if username.lower() in reserved_routes:
        return ""
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", username):
        return ""
    if len(path_parts) > 2:
        return ""

    if len(path_parts) == 2:
        section = path_parts[1]
        if section != "about" and not section.startswith("about_"):
            return ""

    return f"https://www.facebook.com/{username}"


# Tạo URL mục Giới thiệu, giữ ID của kiểu URL profile.php.
def entity_about_url(url: str, kind: str) -> str:
    """Chuyển URL đối tượng thành URL mục Giới thiệu của chính đối tượng đó."""
    base_url = canonical_entity_url(url, kind)
    if not base_url:
        raise ValueError(f"URL {kind} không hợp lệ: {url}")

    if "profile.php?" in base_url:
        return base_url + "&sk=about"

    if kind == "group":
        return base_url + "/about/"

    return base_url + "/about"


def canonical_post_url(href: str) -> str:
    """Chỉ giữ URL bài cụ thể và tham số nhận diện bài; bỏ trang tìm kiếm."""
    if not href:
        return ""

    try:
        absolute_url = urljoin("https://www.facebook.com/", href)
        parsed_url = urlparse(absolute_url)

        if parsed_url.scheme not in {"http", "https"}:
            return ""
        if parsed_url.hostname not in FACEBOOK_HOSTS:
            return ""
    except ValueError:
        return ""

    path = parsed_url.path
    if path == "/search" or path.startswith("/search/"):
        return ""

    route = path.rstrip("/")
    query_parameters = parse_qs(parsed_url.query)
    keys_to_keep = ()

    if route in {"/story.php", "/permalink.php"}:
        if not query_parameters.get("story_fbid"):
            return ""
        keys_to_keep = ("story_fbid", "id")
    elif route in {"/photo", "/photo.php"}:
        if not query_parameters.get("fbid"):
            return ""
        keys_to_keep = ("fbid", "set")
    elif route in {"/watch", "/video.php"}:
        if not query_parameters.get("v"):
            return ""
        keys_to_keep = ("v",)
    else:
        is_post_path = POST_PATH_RE.search(path)
        is_photo_path = PHOTO_PATH_RE.search(path)
        is_shared_post = SHARE_PATH_RE.fullmatch(path)
        if not is_post_path and not is_photo_path and not is_shared_post:
            return ""

    kept_parameters = {}
    for key in keys_to_keep:
        if key in query_parameters:
            kept_parameters[key] = query_parameters[key][0]

    suffix = ""
    if kept_parameters:
        suffix = "?" + urlencode(kept_parameters)

    return f"https://www.facebook.com{path}{suffix}"


# Cùng quy tắc cho bước tìm container trong DOM; /search/posts không phải bài.
POST_URL_JS = r"""
href => {
  try {
    const u = new URL(href, 'https://www.facebook.com/');
    if (!['http:', 'https:'].includes(u.protocol) ||
        !['facebook.com', 'www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com', 'web.facebook.com'].includes(u.hostname)) return false;
    const path = u.pathname;
    if (path === '/search' || path.startsWith('/search/')) return false;
    const route = path.replace(/\/$/, '');
    if (['/story.php', '/permalink.php'].includes(route)) return Boolean(u.searchParams.get('story_fbid'));
    if (['/photo', '/photo.php'].includes(route)) return Boolean(u.searchParams.get('fbid'));
    if (['/watch', '/video.php'].includes(route)) return Boolean(u.searchParams.get('v'));
    return /\/(?:posts|permalink|videos|reel)\/(?:\d+|pfbid[a-zA-Z0-9]+)(?:\/|$)/.test(path) ||
           /\/photos\/(?:[^/]+\/)*(?:\d+|pfbid[a-zA-Z0-9]+)(?:\/|$)/.test(path) ||
           /^\/share\/[pvr]\/[a-zA-Z0-9]+\/?$/.test(path);
  } catch { return false; }
}
"""
