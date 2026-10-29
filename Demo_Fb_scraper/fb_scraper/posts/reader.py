"""Đọc và cuộn nguồn Facebook, trả từng bài hợp lệ cho bên gọi."""
import asyncio
import random

from playwright.async_api import Page

from fb_scraper.common.urls import POST_URL_JS
from fb_scraper.posts.parser import parse_article


# Dùng role=article nếu có; một số phiên bản Facebook bỏ role này và dùng
# data-ad-comet-preview="message" cho nội dung bài viết.
# Khối chuỗi bên dưới là JavaScript chạy trong Chrome qua page.evaluate(), không phải Python.
EXTRACT_JS = """
() => {
  const postLink = __POST_URL_PREDICATE__;
  let roots = [...document.querySelectorAll('div[role="article"]')]
    .filter(el => el.innerText.trim() && !el.parentElement.closest('[role="article"]') &&
      !/^(Comment (by|from)|Reply by|Bình luận (của|dưới tên|bởi)|Trả lời (của|dưới tên))/i.test(el.getAttribute('aria-label') || ''));

  if (!roots.length) {
    const uniqueRoots = new Set();
    for (const message of document.querySelectorAll(
      '[data-ad-comet-preview="message"], [data-ad-preview="message"]'
    )) {
      let node = message;
      while (node && node !== document.body) {
        const hasPostLink = [...node.querySelectorAll('a[href]')]
          .some(a => postLink(a.href));
        if (hasPostLink && node.querySelectorAll('[role="button"]').length >= 3) {
          uniqueRoots.add(node);
          break;
        }
        node = node.parentElement;
      }
    }
    roots = [...uniqueRoots];
  }

  // Giao diện profile mới có thể bỏ cả role=article lẫn data-ad-preview.
  // Tìm thẻ bài bao quanh permalink, tiêu đề tác giả và hàng nút tương tác.
  if (!roots.length) {
    const uniqueRoots = new Set();
    for (const link of document.querySelectorAll('a[href]')) {
      if (!postLink(link.href)) continue;
      let node = link.parentElement;
      while (node && node !== document.body && node.getAttribute('role') !== 'main') {
        if (node.querySelector('h2, h3, h4, strong a') &&
            node.querySelectorAll('[role="button"]').length >= 3 && node.innerText.trim().length >= 20) {
          uniqueRoots.add(node);
          break;
        }
        node = node.parentElement;
      }
    }
    roots = [...uniqueRoots].filter(node => ![...uniqueRoots].some(other => node !== other && node.contains(other)));
  }

  return roots.map(el => ({
    public_post: [...el.querySelectorAll('[aria-label], [title]')]
      .some(node => /^(?:Công khai|Public|Đã chia sẻ với Công khai|Shared with Public)$/i.test((node.getAttribute('aria-label') || node.getAttribute('title') || '').trim())),
    text: [...new Set([...el.querySelectorAll(
      '[data-ad-comet-preview="message"], [data-ad-preview="message"]'
    )].map(message => message.innerText.trim()).filter(Boolean))].join('\\n') ||
      [...el.querySelectorAll('blockquote')].filter(node => node.getClientRects().length && node.innerText.trim().length >= 20 &&
        !/^(Comment|Reply|Bình luận|Trả lời)/i.test(node.closest('[role="article"][aria-label]')?.getAttribute('aria-label') || ''))
        .map(node => node.innerText.trim()).filter(Boolean).join('\\n') ||
      [...new Set([...el.querySelectorAll('div[dir="auto"]')].filter(node => node.getClientRects().length &&
        node.innerText.trim().length >= 20 && !node.closest('h2, h3, h4, a, [role="button"]') &&
        !/^(Comment|Reply|Bình luận|Trả lời)/i.test(node.closest('[role="article"][aria-label]')?.getAttribute('aria-label') || ''))
        .map(node => node.innerText.trim()))].join('\\n') || el.innerText || '',
    stats_text: el.innerText || '',
    author: (el.querySelector('h2 a, h3 a, h4 a, strong a, h2 span, h3 span') || {}).innerText || '',
    links: [...el.querySelectorAll('a[href]')].map(a => ({href: a.href, text: (a.innerText||'').trim()})),
    imgs: [...el.querySelectorAll('img[src]')].map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight})),
  }));
}
""".replace("__POST_URL_PREDICATE__", POST_URL_JS)


# Chờ ngẫu nhiên từ a đến b giây giữa các thao tác, không chặn vòng lặp asyncio.
async def human_pause(a=1.5, b=4.0):
    await asyncio.sleep(random.uniform(a, b))


# Bấm tối đa 15 nút "Xem thêm/See more" để mở nội dung bị thu gọn trên trang.
async def expand_see_more(page: Page):
    """Bấm tối đa 15 nút mở rộng nội dung đang bị thu gọn."""
    selector = 'div[role="button"]:text-matches("^(Xem thêm|See more)$")'
    buttons = page.locator(selector)
    button_count = await buttons.count()
    maximum_buttons = min(button_count, 15)

    for index in range(maximum_buttons):
        try:
            button = buttons.nth(index)
            await button.click(timeout=1000)
        except Exception:
            # Facebook có thể thay DOM khiến một nút vừa biến mất.
            pass


# Mở nguồn, đọc và cuộn trang; yield từng bài không trùng để main có thể lưu ngay.
# Dừng khi đủ số bài, không có bài mới qua max_idle lượt hoặc gặp đăng nhập/checkpoint.
async def iter_source_posts(page: Page, src: dict, max_posts: int, max_idle: int = 4):
    """Đọc từng bài rồi yield ngay, giúp bên gọi lưu trước khi tiếp tục cuộn."""
    response = await page.goto(src["url"], wait_until="domcontentloaded")
    await human_pause(3, 5)

    response_status = "không có response"
    if response:
        response_status = response.status

    page_title = await page.title()
    print(f"  URL hiện tại: {page.url}")
    print(f"  HTTP: {response_status}")
    print(f"  Tiêu đề: {page_title}")

    seen_post_ids = set()
    idle_turns = 0
    maximum_articles = 0

    while len(seen_post_ids) < max_posts and idle_turns < max_idle:
        if "checkpoint" in page.url or "login" in page.url:
            print("[!] Facebook yêu cầu đăng nhập/xác minh -> dừng, hãy xử lý tay trên Chrome.")
            break

        await expand_see_more(page)
        new_posts_count = 0
        raw_posts = await page.evaluate(EXTRACT_JS)
        maximum_articles = max(maximum_articles, len(raw_posts))

        for raw_post in raw_posts:
            if src.get("public_only") and not raw_post.get("public_post"):
                continue

            post = parse_article(raw_post, src["name"])
            if post is None:
                continue
            if post["post_id"] in seen_post_ids:
                continue

            seen_post_ids.add(post["post_id"])
            new_posts_count += 1

            # Tạm trả một bài cho collect_source_posts() lưu; lần lặp sau mới đọc tiếp.
            yield post

            if len(seen_post_ids) >= max_posts:
                break

        if new_posts_count == 0:
            idle_turns += 1
        else:
            idle_turns = 0

        print(
            f"  Lượt quét: {len(raw_posts)} article, {new_posts_count} bài mới, "
            f"{len(seen_post_ids)} bài hợp lệ",
            flush=True,
        )
        if len(seen_post_ids) >= max_posts:
            break

        scroll_distance = random.randint(1800, 3000)
        await page.mouse.wheel(0, scroll_distance)
        await human_pause()

    print(f"  Article tìm thấy nhiều nhất trong một lượt: {maximum_articles}")
    print(f"  Bài hợp lệ đã trích xuất: {len(seen_post_ids)}")
    if not seen_post_ids:
        print("[!] Không trích xuất được bài nào. Kiểm tra URL/đăng nhập hoặc cấu trúc bài viết trên Facebook.")
