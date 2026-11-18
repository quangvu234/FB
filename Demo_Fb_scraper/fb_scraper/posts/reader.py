"""Đọc và cuộn nguồn Facebook, trả từng bài hợp lệ cho bên gọi."""
import random

from playwright.async_api import Page

from fb_scraper.common.page_actions import expand_see_more, human_pause
from fb_scraper.common.content import is_collapsed_text
from fb_scraper.posts.details import complete_post
from fb_scraper.common.urls import POST_URL_JS, is_login_url
from fb_scraper.posts.labels import COMMENT_LABEL_JS
from fb_scraper.posts.parser import parse_article


# Facebook giấu permalink ở link thời gian (href="?__cft__..." hoặc "#") và chỉ điền
# URL thật khi link được rê chuột/focus. Script này phát sự kiện focus/mouseover cho
# các link đó để React điền href, không cần di chuột thật và không bấm vào link.
REVEAL_LINKS_JS = r"""() => {
  const hidden = document.querySelectorAll('[role="main"] a[href^="?"], [role="main"] a[href="#"]');
  for (const link of hidden) {
    link.dispatchEvent(new FocusEvent('focusin', {bubbles: true}));
    link.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
  }
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  return hidden.length;
}"""

# Khối chuỗi bên dưới là JavaScript chạy trong Chrome qua page.evaluate(), không phải Python.
# Tìm khung bài theo 4 cách, dùng cách sau khi cách trước không ra kết quả:
#   1. div[role="article"] (giao diện cũ);
#   2. các thẻ con trực tiếp của role=feed (trang tìm kiếm/nhóm hiện tại);
#   3. đi ngược từ data-ad-comet-preview="message" (nội dung bài) lên khung có permalink;
#   4. đi ngược từ permalink lên khung có tiêu đề tác giả và hàng nút tương tác.
EXTRACT_JS = r"""
() => {
  const postLink = __POST_URL_PREDICATE__;
  const commentLabel = __COMMENT_LABEL__;
  // Vùng bình luận: nhãn bắt đầu bằng Comment/Reply/Bình luận/Trả lời.
  const commentArea = /^(Comment|Reply|Bình luận|Trả lời)/i;
  const MESSAGE = '[data-ad-comet-preview="message"], [data-ad-preview="message"]';

  const inComment = node =>
    commentArea.test(node.closest('[role="article"][aria-label]')?.getAttribute('aria-label') || '');
  const visibleLongText = node => node.getClientRects().length && node.innerText.trim().length >= 20;
  const unique = items => [...new Set(items.filter(Boolean))];
  const contentText = node => {
    let text = node.innerText.trim();
    for (const control of node.querySelectorAll('button, [role="button"], a')) {
      const label = control.innerText?.trim() || '';
      if (/^(?:Xem bớt|Ẩn bớt|See less)$/i.test(label)) {
        const index = text.lastIndexOf(label);
        if (index >= 0) text = text.slice(0, index) + text.slice(index + label.length);
      }
    }
    return text.trim();
  };

  function findRoots() {
    const articles = [...document.querySelectorAll('div[role="article"]')].filter(el =>
      el.innerText.trim() && !el.parentElement.closest('[role="article"]') &&
      !commentLabel.test(el.getAttribute('aria-label') || ''));
    if (articles.length) return articles;

    // Trang tìm kiếm/nhóm mới: mỗi bài là một thẻ con trực tiếp của role=feed.
    const feedItems = [...document.querySelectorAll('[role="feed"] > *')].filter(el =>
      el.innerText.trim().length >= 20 && el.querySelectorAll('[role="button"]').length >= 3);
    if (feedItems.length) return feedItems;

    const fromMessages = new Set();
    for (const message of document.querySelectorAll(MESSAGE)) {
      for (let node = message; node && node !== document.body; node = node.parentElement) {
        const hasPostLink = [...node.querySelectorAll('a[href]')].some(a => postLink(a.href));
        if (hasPostLink && node.querySelectorAll('[role="button"]').length >= 3) {
          fromMessages.add(node);
          break;
        }
      }
    }
    if (fromMessages.size) return [...fromMessages];

    // Giao diện profile mới có thể bỏ cả role=article lẫn data-ad-preview.
    const fromLinks = new Set();
    for (const link of document.querySelectorAll('a[href]')) {
      if (!postLink(link.href)) continue;
      let node = link.parentElement;
      while (node && node !== document.body && node.getAttribute('role') !== 'main') {
        if (node.querySelector('h2, h3, h4, strong a') &&
            node.querySelectorAll('[role="button"]').length >= 3 && node.innerText.trim().length >= 20) {
          fromLinks.add(node);
          break;
        }
        node = node.parentElement;
      }
    }
    // Chỉ giữ khung nhỏ nhất, bỏ khung ngoài đang chứa một khung bài khác.
    return [...fromLinks].filter(node => ![...fromLinks].some(other => node !== other && node.contains(other)));
  }

  // Nội dung bài: ưu tiên vùng message, rồi blockquote, rồi các khối chữ dài, cuối cùng là toàn bộ khung.
  function readText(el) {
    const messages = unique([...el.querySelectorAll(MESSAGE)].filter(node => !inComment(node)).map(contentText));
    if (messages.length) return messages.join('\n');

    const quotes = [...el.querySelectorAll('blockquote')]
      .filter(node => visibleLongText(node) && !inComment(node))
      .map(contentText).filter(Boolean);
    if (quotes.length) return quotes.join('\n');

    const blocks = unique([...el.querySelectorAll('div[dir="auto"]')]
      .filter(node => visibleLongText(node) && !node.closest('h2, h3, h4, a, [role="button"]') && !inComment(node))
      .map(contentText));
    if (blocks.length) return blocks.join('\n');

    return el.innerText || '';
  }

  const PUBLIC_LABEL = /^(?:Công khai|Public|Đã chia sẻ với Công khai|Shared with Public)$/i;

  return findRoots().map(el => {
    const authorNode = [...el.querySelectorAll('a[href*="/user/"]')].find(a => a.innerText.trim() && !inComment(a)) ||
      el.querySelector('h2 a, h3 a, h4 a, strong a, h2 span, h3 span');
    const authorLink = authorNode?.closest('a') || authorNode?.querySelector('a');
    const shared = [...el.querySelectorAll('[data-shared-post], [role="article"]')]
      .find(node => !inComment(node) && !commentLabel.test(node.getAttribute('aria-label') || ''));
    const original = shared ? [...shared.querySelectorAll('a[href]')].find(a => postLink(a.href)) : null;
    return {
    public_post: [...el.querySelectorAll('[aria-label], [title]')]
      .some(node => PUBLIC_LABEL.test((node.getAttribute('aria-label') || node.getAttribute('title') || '').trim())),
    text: readText(el),
    stats_text: el.innerText || '',
    // aria-label chứa số liệu có nhãn rõ: "..., 12 bình luận", "Thích: 8 người", "... của <tác giả>".
    labels: [...new Set([...el.querySelectorAll('[aria-label]')].map(node => node.getAttribute('aria-label')))],
    // Bài trong nhóm: người đăng là link /groups/<id>/user/<uid>; tiêu đề h2/h3 là tên nhóm.
    author: authorNode?.innerText || '',
    author_url: authorLink?.href || '',
    is_shared: Boolean(shared),
    original_post_url: original?.href || '',
    links: [...el.querySelectorAll('a[href]')].map(a => ({href: a.href, text: (a.innerText || '').trim()})),
    imgs: [...el.querySelectorAll('img[src]')].map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight})),
    videos: [...el.querySelectorAll('video')].filter(v => !inComment(v))
      .map(v => v.currentSrc || v.src || v.querySelector('source')?.src || '').filter(url => /^https?:/.test(url)),
  };});
}
""".replace("__POST_URL_PREDICATE__", POST_URL_JS).replace("__COMMENT_LABEL__", COMMENT_LABEL_JS)


# Mở nguồn, đọc và cuộn trang; yield từng bài không trùng để bên gọi có thể lưu ngay.
# Dừng khi đủ số bài, không có bài mới qua max_idle lượt hoặc gặp đăng nhập/checkpoint.
async def iter_source_posts(page: Page, source: dict, max_posts: int, max_idle: int = 4):
    """Đọc từng bài rồi yield ngay, giúp bên gọi lưu trước khi tiếp tục cuộn."""
    response = await page.goto(source["url"], wait_until="domcontentloaded")
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
        if is_login_url(page.url):
            print("[!] Facebook yêu cầu đăng nhập/xác minh -> dừng, hãy xử lý tay trên Chrome.")
            break

        await expand_see_more(page)
        hidden_links = await page.evaluate(REVEAL_LINKS_JS)
        if hidden_links:
            # Chờ React điền URL thật vào các link vừa được focus.
            await human_pause(0.5, 1)

        new_posts_count = 0
        raw_posts = await page.evaluate(EXTRACT_JS)
        maximum_articles = max(maximum_articles, len(raw_posts))

        for raw_post in raw_posts:
            if source.get("public_only") and not raw_post.get("public_post"):
                continue

            post = parse_article(raw_post, source["name"])
            if post is None:
                continue
            if post["post_id"] in seen_post_ids:
                continue
            if is_collapsed_text(post.get("text")) or not post.get("author"):
                post = await complete_post(page, post)

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
