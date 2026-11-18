"""Đọc và tải thêm bình luận trong tab riêng."""
import re

from playwright.async_api import BrowserContext, Page

from fb_scraper.common.comments import comment_key, merge_comment_records, normalize_comments
from fb_scraper.common.content import comment_author, is_collapsed_text
from fb_scraper.common.page_actions import expand_see_more, human_pause
from fb_scraper.common.urls import canonical_post_url, is_login_url
from fb_scraper.posts.comment_reader import EXTRACT_COMMENTS_JS
from fb_scraper.posts.labels import COMMENT_LABEL_JS, COMMENT_LABEL_RE
from fb_scraper.posts.parser import parse_relative_time


COMMENT_MORE_RE = re.compile(
    r"^\s*(?:Xem thêm bình luận|Xem (?:các )?bình luận trước|Xem bình luận khác|"
    r"Xem \d+ bình luận (?:khác|nữa)|Hiển thị thêm bình luận|"
    r"(?:View|See|Load) (?:more|previous|\d+ more) comments)[\s\ufeff]*$", re.I
)
REPLY_MORE_RE = re.compile(
    r"^\s*(?:Xem (?:thêm |tất cả )?(?:\d+ )?(?:câu trả lời|phản hồi)|"
    r"(?:View|See|Load) (?:(?:all|more|previous) )?(?:\d+ )?(?:more )?repl(?:y|ies))\s*$", re.I
)
# JavaScript cuộn vùng chứa bình luận; cuộn trang nếu không tìm thấy vùng cuộn riêng.
SCROLL_COMMENTS_JS = r"""() => {
  const comments = [...document.querySelectorAll('[role="article"][aria-label]')]
    .filter(el => __COMMENT_LABEL__.test(el.getAttribute('aria-label') || ''));
  let node = comments.at(-1)?.parentElement;
  while (node && node !== document.body) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) {
      node.scrollTop += Math.max(500, node.clientHeight * 0.8);
      return;
    }
    node = node.parentElement;
  }
  window.scrollBy(0, 700);
}""".replace("__COMMENT_LABEL__", COMMENT_LABEL_JS)


# Lọc nhãn bình luận và cập nhật dictionary collected theo ID để loại trùng trong lượt đọc.
def merge_comments(collected: dict, raw_comments: list):
    """Giữ ID và quan hệ trả lời thay vì chỉ trả về nội dung chuỗi."""
    incoming = []
    for raw_comment in raw_comments:
        label = raw_comment.get("label", "")
        if not COMMENT_LABEL_RE.match(label):
            continue

        text = raw_comment.get("text", "").strip()
        if not text:
            continue

        record = {key: value for key, value in raw_comment.items() if key not in {"id", "label"}}
        record.update(comment_id=raw_comment.get("id"), text=text)
        record["author"] = record.get("author") or comment_author(label)
        if not record.get("created_at"):
            record["created_at"] = parse_relative_time(record.get("posted_raw") or "")
        if "is_reply" not in record:
            record["is_reply"] = bool(re.match(r"^\s*(Reply by|Trả lời)", label, re.I))
        incoming.append(record)
    for comment in merge_comment_records(list(collected.values()), incoming):
        collected[comment_key(comment)] = comment


# Tìm và bấm nút tải thêm bình luận; trả True nếu bấm được, ngược lại trả False.
async def click_more(page: Page, pattern):
    buttons = page.locator('[role="button"], a').filter(has_text=pattern)
    for index in range(min(await buttons.count(), 5)):
        button = buttons.nth(index)
        try:
            if await button.is_visible():
                await button.click(timeout=2500)
                return True
        except Exception:
            continue
    return False


async def expand_replies(page: Page):
    return await click_more(page, REPLY_MORE_RE)


async def load_more_comments(page: Page):
    return await click_more(page, COMMENT_MORE_RE)


# Mở permalink trong tab phụ, đọc tối đa n bản ghi (gồm bình luận gốc và reply).
# Giữ kết quả đã đọc nếu có lỗi và luôn đóng tab phụ sau khi xử lý.
async def scrape_top_comments(context: BrowserContext, url: str, n: int):
    """Mở tab phụ để lấy tối đa n bình luận; lỗi về sau không xóa kết quả đã đọc."""
    if n <= 0:
        return []

    post_url = canonical_post_url(url)
    if not post_url:
        print("  Bỏ qua bình luận: chưa có permalink bài viết hợp lệ.")
        return []

    page = await context.new_page()
    collected_comments = {}

    try:
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await human_pause(2.5, 4)
        idle_turns = 0
        incomplete_turns = 0
        maximum_turns = max(6, n // 5 + 5)

        for turn in range(maximum_turns):
            if is_login_url(page.url):
                print("  Facebook yêu cầu đăng nhập/xác minh khi lấy bình luận.")
                break

            await expand_see_more(page)
            # Mở một nhánh reply trước khi xét giới hạn; tránh chỉ đếm đủ bình luận gốc.
            if await expand_replies(page):
                await human_pause(0.5, 1)
                # Các reply vừa tải cũng có thể chứa nút mở nội dung dài.
                await expand_see_more(page)
            previous_count = len(collected_comments)
            raw_comments = await page.evaluate(EXTRACT_COMMENTS_JS)
            merge_comments(collected_comments, raw_comments)
            incomplete = any(is_collapsed_text(comment["text"]) for comment in list(collected_comments.values())[:n])
            incomplete_turns = incomplete_turns + 1 if incomplete else 0
            if incomplete:
                print("  Một số bình luận chưa mở hết nội dung; sẽ thử mở lại ở lượt đọc tiếp theo.", flush=True)

            displayed_count = min(len(collected_comments), n)
            print(f"  Bình luận đã đọc: {displayed_count}/{n}", flush=True)
            if len(collected_comments) >= n and (not incomplete or incomplete_turns >= 3):
                break

            if len(collected_comments) == previous_count:
                idle_turns += 1
            else:
                idle_turns = 0

            if idle_turns >= 3:
                break

            loaded_more = await load_more_comments(page)
            if not loaded_more:
                await page.evaluate(SCROLL_COMMENTS_JS)
            await human_pause(1, 2)

        if not collected_comments:
            print("  Chưa đọc được bình luận trên trang bài viết; kiểm tra quyền xem hoặc phần bình luận trên Chrome.")
        elif len(collected_comments) < n:
            print(f"  Đã lấy {len(collected_comments)}/{n} bình luận; giao diện chưa tải thêm bình luận.")

    except Exception as error:
        print(f"  Lỗi đọc bình luận ({type(error).__name__}); giữ {len(collected_comments)} bình luận đã đọc.")
    finally:
        await page.close()

    return normalize_comments(list(collected_comments.values()))[:n]
