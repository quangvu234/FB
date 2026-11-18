"""Làm sạch dữ liệu bài viết trong bộ nhớ; không mở Chrome hay ghi file."""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fb_scraper.common.numbers import parse_count
from fb_scraper.common.urls import canonical_post_url, make_post_id
from fb_scraper.common.models import Post

# Ký tự ẩn Facebook chèn vào chữ bị xáo trộn (chống đọc tự động).
HIDDEN_CHAR = "\u034f"
# Ví dụ: "Thứ Ba, 10 Tháng 11, 2026 lúc 08:03".
VIETNAMESE_DATE_RE = re.compile(r"(\d{1,2}) Tháng (\d{1,2}),? (\d{4})(?: lúc (\d{1,2}):(\d{2}))?", re.I)
# Ví dụ aria-label: "Thích: 14 người", "Yêu thích: 1 người", "Like: 3 people".
REACTION_LABEL_RE = re.compile(r"^[^:,]{1,20}:\s*(\d[\d.,]*\s*(?:[KkMmNn]|Tr)?)\s*(?:người|people|person)$", re.I)
# Ví dụ aria-label: "Hành động đối với bài viết này của Việt Anh".
AUTHOR_LABEL_RE = re.compile(r"^(?:Hành động đối với bài viết này của|Actions for this post by)\s+(.+)$", re.I)


# Chọn liên kết bài viết phù hợp nhất trong danh sách; trả về None nếu không có permalink.
def find_post_link(links):
    """Chọn permalink tốt nhất: link bài trước link bình luận, rồi thời gian đăng."""
    valid_links = []
    for link in links:
        canonical_url = canonical_post_url(link.get("href", ""))
        if canonical_url:
            valid_links.append(link)

    if not valid_links:
        return None

    def rank(link):
        canonical_url = canonical_post_url(link["href"])
        query_parameters = parse_qs(urlparse(link["href"]).query)

        comment_priority = 0
        if "comment_id" in query_parameters or "reply_comment_id" in query_parameters:
            comment_priority = 1

        time_priority = 1
        if parse_relative_time(link.get("text", "")):
            time_priority = 0

        permalink_priority = 1
        if re.search(r"/(?:posts|permalink)/|story_fbid=", canonical_url):
            permalink_priority = 0

        # Python so sánh tuple từ trái sang phải; giá trị 0 được ưu tiên trước 1.
        return (comment_priority, time_priority, permalink_priority)

    best_link = valid_links[0]
    best_rank = rank(best_link)

    for link in valid_links[1:]:
        current_rank = rank(link)
        if current_rank < best_rank:
            best_link = link
            best_rank = current_rank

    return best_link


# Đổi thời gian tương đối thành ISO UTC ước lượng; trả về None với định dạng không hỗ trợ.
def parse_relative_time(raw: str):
    """Đổi '2 giờ', '3 ngày', '2h' thành thời gian UTC ước lượng."""
    time_pattern = r"(\d+)\s*(phút|giờ|ngày|tuần|m|h|d|w|min|hr|hrs)\b"
    match = re.match(time_pattern, raw.strip(), re.I)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    time_units = {
        "phút": "minutes", "m": "minutes", "min": "minutes",
        "giờ": "hours", "h": "hours", "hr": "hours", "hrs": "hours",
        "ngày": "days", "d": "days",
        "tuần": "weeks", "w": "weeks",
    }
    time_unit = time_units[unit]

    if time_unit == "minutes":
        elapsed_time = timedelta(minutes=amount)
    elif time_unit == "hours":
        elapsed_time = timedelta(hours=amount)
    elif time_unit == "days":
        elapsed_time = timedelta(days=amount)
    else:
        elapsed_time = timedelta(weeks=amount)

    current_time = datetime.now(timezone.utc)
    posted_time = current_time - elapsed_time
    return posted_time.isoformat()


def parse_vietnamese_date(raw: str):
    """Đổi "10 Tháng 11, 2026 lúc 08:03" (giờ của máy) thành ISO UTC; không khớp thì None."""
    match = VIETNAMESE_DATE_RE.search(raw)
    if not match:
        return None

    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    try:
        local_time = datetime(year, month, day, hour, minute).astimezone()
    except ValueError:
        return None
    return local_time.astimezone(timezone.utc).isoformat()


def find_posted_time(card_text: str, post_text: str):
    """Tìm mốc thời gian đọc được ở phần đầu khung bài (trước nội dung bài).

    Trả (chuỗi gốc, ISO UTC) hoặc ("", None). Chỉ xét phần trước nội dung để
    câu như "3 ngày nữa..." trong bài không bị nhận nhầm là thời gian đăng.
    """
    header = card_text
    content_start = card_text.find(post_text[:30]) if post_text else -1
    if content_start > 0:
        header = card_text[:content_start]

    for line in header.splitlines():
        line = line.strip()
        if not line or HIDDEN_CHAR in line:
            continue
        posted_at = parse_vietnamese_date(line) or parse_relative_time(line)
        if posted_at:
            return line, posted_at
    return "", None


def author_from_labels(labels):
    """Lấy tên người đăng từ aria-label, kể cả "Người tham gia ẩn danh"."""
    for label in labels:
        match = AUTHOR_LABEL_RE.match(label.strip())
        if match:
            return match.group(1).strip()
    return ""


def reaction_total(labels):
    """Cộng các nhãn "Thích: 14 người", "Yêu thích: 1 người" thành tổng cảm xúc."""
    total = None
    for label in labels:
        match = REACTION_LABEL_RE.match(label.strip())
        if match:
            count = parse_count(match.group(1))
            if count is not None:
                total = (total or 0) + count
    return total


# Đọc số cảm xúc, bình luận và chia sẻ từ văn bản; trả tuple gồm ba số hoặc None.
def parse_counts(text: str):
    """Trả về (số cảm xúc, số bình luận, số chia sẻ); trường không thấy là None."""
    number_pattern = r"(\d[\d.,]*\s*(?:[KkMmNn]|Tr)?)"
    likes_match = re.search(r"(?:Tất cả cảm xúc|All reactions)[:\s]*" + number_pattern, text)
    comments_match = re.search(number_pattern + r"\s*(?:bình luận|comments?)", text, re.I)
    shares_match = re.search(number_pattern + r"\s*(?:lượt chia sẻ|shares?)", text, re.I)

    counts = []
    for match in (likes_match, comments_match, shares_match):
        if match:
            counts.append(parse_count(match.group(1)))
        else:
            counts.append(None)

    return tuple(counts)


# Chuẩn hóa dữ liệu DOM thành dictionary bài viết; bỏ nội dung ngắn dưới 20 ký tự.
def parse_article(raw: dict, source: str):
    """Đổi dữ liệu DOM thành bài viết; chưa mở tab, tải ảnh hay ghi database."""
    text = raw["text"].strip()
    if len(text) < 20:
        return None

    post_link = find_post_link(raw["links"])
    post_url = ""
    posted_raw = ""

    if post_link:
        post_url = canonical_post_url(post_link["href"])
        query_parameters = parse_qs(urlparse(post_link["href"]).query)
        is_comment_link = False

        if "comment_id" in query_parameters or "reply_comment_id" in query_parameters:
            is_comment_link = True

        # Facebook có thể xáo trộn chữ của mốc thời gian và chèn ký tự ẩn U+034F
        # để chống đọc tự động; chuỗi đó không đọc được nên để trống.
        if not is_comment_link and HIDDEN_CHAR not in post_link["text"]:
            posted_raw = post_link["text"]

    card_text = raw.get("stats_text", text)
    labels = raw.get("labels", [])
    # aria-label có nhãn rõ ràng nên được đọc cùng chữ hiển thị của khung bài.
    likes, comments, shares = parse_counts(card_text + "\n" + "\n".join(labels))
    if likes is None:
        likes = reaction_total(labels)

    posted_at = parse_relative_time(posted_raw)
    if not posted_at:
        posted_raw, posted_at = find_posted_time(card_text, text)

    image_urls = []
    seen_image_urls = set()
    for image in raw["imgs"]:
        image_url = image["src"]
        if "scontent" not in image_url:
            continue
        if image["w"] < 200 or image["h"] < 200:
            continue

        if image_url not in seen_image_urls:
            seen_image_urls.add(image_url)
            image_urls.append(image_url)

    external_urls = set()
    for link in raw["links"]:
        link_url = link["href"]
        is_redirect_link = "l.facebook.com/l.php" in link_url
        is_external_link = link_url.startswith("http") and "facebook.com" not in link_url

        if is_redirect_link or is_external_link:
            external_urls.add(link_url)

    record = {
        "post_id": make_post_id(post_url, text),
        "url": post_url,
        "source": source,
        "author": author_from_labels(labels) or raw["author"].strip(),
        "text": text,
        "posted_raw": posted_raw,
        "posted_at": posted_at,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "links": sorted(external_urls),
        "images": image_urls,
    }
    record["author_url"] = raw.get("author_url", "")
    if "is_shared" in raw:
        record["is_shared"] = bool(raw["is_shared"])
    original_url = canonical_post_url(raw.get("original_post_url", ""))
    if original_url and original_url != post_url:
        record.update(is_shared=True, original_post_key=make_post_id(original_url, ""))
    record["media"] = [{"media_type": "video", "media_url": url, "position": index}
                       for index, url in enumerate(raw.get("videos", [])) if url.startswith(("http://", "https://"))]
    validated_post = Post.model_validate(record)
    return validated_post.model_dump(exclude_unset=True)
