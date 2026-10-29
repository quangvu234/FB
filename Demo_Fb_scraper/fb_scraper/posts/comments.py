"""Đọc và tải thêm bình luận trong tab riêng."""
import re

from playwright.async_api import BrowserContext, Page

from fb_scraper.common.urls import canonical_post_url
from fb_scraper.posts.reader import expand_see_more, human_pause


COMMENT_LABEL_RE = re.compile(
    r"^\s*(?:Comment (?:by|from)|Reply by|Bình luận (?:của|dưới tên|bởi)|Trả lời (?:của|dưới tên))\b", re.I
)
COMMENT_MORE_RE = re.compile(
    r"^\s*(?:Xem thêm bình luận|Xem (?:các )?bình luận trước|Xem bình luận khác|"
    r"Xem \d+ bình luận (?:khác|nữa)|Hiển thị thêm bình luận|"
    r"(?:View|See|Load) (?:more|previous|\d+ more) comments)[\s\ufeff]*$", re.I
)
# JavaScript đọc ID, nhãn aria-label và nội dung của các phần tử bình luận trong DOM.
EXTRACT_COMMENTS_JS = r"""() => [...document.querySelectorAll('[role="article"][aria-label]')].map(el => {
  const ids = [...el.querySelectorAll('a[href*="comment_id"]')].map(a => {
    try { return new URL(a.href).searchParams.get('comment_id'); } catch { return null; }
  }).filter(Boolean);
  return {
    id: ids.find(id => /^\d+$/.test(id)) || ids[0] || '',
    label: el.getAttribute('aria-label') || '',
    text: (el.innerText || '').trim(),
  };
})"""
# JavaScript cuộn vùng chứa bình luận; cuộn trang nếu không tìm thấy vùng cuộn riêng.
SCROLL_COMMENTS_JS = r"""() => {
  const comments = [...document.querySelectorAll('[role="article"][aria-label]')]
    .filter(el => /^(Comment (by|from)|Reply by|Bình luận (của|dưới tên|bởi)|Trả lời (của|dưới tên))/i.test(el.getAttribute('aria-label') || ''));
  let node = comments.at(-1)?.parentElement;
  while (node && node !== document.body) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight) {
      node.scrollTop += Math.max(500, node.clientHeight * 0.8);
      return;
    }
    node = node.parentElement;
  }
  window.scrollBy(0, 700);
}"""


# Lọc nhãn bình luận và cập nhật dictionary collected theo ID để loại trùng trong lượt đọc.
def merge_comments(collected: dict, raw_comments: list):
    """Cập nhật bình luận theo ID; cùng ID sẽ nhận nội dung đầy đủ đọc được mới nhất."""
    for raw_comment in raw_comments:
        label = raw_comment.get("label", "")
        if not COMMENT_LABEL_RE.match(label):
            continue

        text = raw_comment.get("text", "").strip()
        if not text:
            continue

        comment_id = raw_comment.get("id")
        if not comment_id:
            comment_id = raw_comment["label"] + "\n" + text

        collected[comment_id] = text


# Tìm và bấm nút tải thêm bình luận; trả True nếu bấm được, ngược lại trả False.
async def load_more_comments(page: Page):
    buttons = page.locator('[role="button"], a').filter(has_text=COMMENT_MORE_RE)
    for index in range(min(await buttons.count(), 5)):
        button = buttons.nth(index)
        try:
            if await button.is_visible():
                await button.click(timeout=2500)
                return True
        except Exception:
            continue
    return False


# Mở permalink trong tab phụ, đọc và tải thêm tối đa n bình luận rồi trả danh sách nội dung.
# Giữ kết quả đã đọc nếu có lỗi và luôn đóng tab phụ sau khi xử lý.
async def scrape_top_comments(ctx: BrowserContext, url: str, n: int):
    """Mở tab phụ để lấy tối đa n bình luận; lỗi về sau không xóa kết quả đã đọc."""
    if n <= 0:
        return []

    post_url = canonical_post_url(url)
    if not post_url:
        print("  Bỏ qua bình luận: chưa có permalink bài viết hợp lệ.")
        return []

    page = await ctx.new_page()
    collected_comments = {}

    try:
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await human_pause(2.5, 4)
        idle_turns = 0
        maximum_turns = max(6, n // 5 + 5)

        for turn in range(maximum_turns):
            if "checkpoint" in page.url or "login" in page.url:
                print("  Facebook yêu cầu đăng nhập/xác minh khi lấy bình luận.")
                break

            await expand_see_more(page)
            previous_count = len(collected_comments)
            raw_comments = await page.evaluate(EXTRACT_COMMENTS_JS)
            merge_comments(collected_comments, raw_comments)

            displayed_count = min(len(collected_comments), n)
            print(f"  Bình luận đã đọc: {displayed_count}/{n}", flush=True)
            if len(collected_comments) >= n:
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

    comment_texts = list(collected_comments.values())
    return comment_texts[:n]
