"""Làm sạch dữ liệu bài viết trong bộ nhớ; không mở Chrome hay ghi file."""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fb_scraper.common.urls import canonical_post_url, make_post_id
from fb_scraper.common.models import Post


# Chuyển số hiển thị trên Facebook thành số nguyên; trả về None nếu không nhận diện được.
def to_int(s):
    """Đổi số hiển thị: '1,2K' -> 1200, '1.234' -> 1234; không đọc được thì trả None."""
    if not s:
        return None

    number_text = s.strip().replace("\u00a0", " ")
    match = re.match(r"([\d.,]+)\s*([KkMmNnTr]*)", number_text)
    if not match:
        return None

    digits = match.group(1)
    suffix = match.group(2).lower()
    multiplier = 1

    if suffix in ("k", "n"):
        multiplier = 1000
    elif suffix in ("m", "tr"):
        multiplier = 1000000

    if multiplier > 1:
        decimal_digits = digits.replace(",", ".")
        return int(float(decimal_digits) * multiplier)

    integer_digits = re.sub(r"[.,]", "", digits)
    return int(integer_digits)


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


# Đọc số cảm xúc, bình luận và chia sẻ từ văn bản; trả tuple gồm ba số hoặc None.
def parse_counts(text: str):
    """Trả về (số cảm xúc, số bình luận, số chia sẻ); trường không thấy là None."""
    number_pattern = r"([\d.,]+\s*(?:[KkMmNn]|Tr)?)"
    likes_match = re.search(r"(?:Tất cả cảm xúc|All reactions)[:\s]*" + number_pattern, text)
    comments_match = re.search(number_pattern + r"\s*(?:bình luận|comments?)", text, re.I)
    shares_match = re.search(number_pattern + r"\s*(?:lượt chia sẻ|shares?)", text, re.I)

    likes_count = None
    comments_count = None
    shares_count = None

    if likes_match:
        likes_count = to_int(likes_match.group(1))
    if comments_match:
        comments_count = to_int(comments_match.group(1))
    if shares_match:
        shares_count = to_int(shares_match.group(1))

    return likes_count, comments_count, shares_count


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

        if not is_comment_link:
            posted_raw = post_link["text"]

    statistics_text = raw.get("stats_text", text)
    likes, comments, shares = parse_counts(statistics_text)

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
        "author": raw["author"].strip(),
        "text": text,
        "posted_raw": posted_raw,
        "posted_at": parse_relative_time(posted_raw),
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "links": sorted(external_urls),
        "images": image_urls,
    }
    validated_post = Post.model_validate(record)
    return validated_post.model_dump(exclude_unset=True)
