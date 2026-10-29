"""Đọc và cuộn kết quả tìm kiếm; trả từng URL đã chuẩn hóa."""
import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from fb_scraper.common.urls import canonical_entity_url


# Đọc liên kết tên trong vùng kết quả, tránh nút thao tác, menu và liên kết trong phần mô tả.
# Đây là chuỗi JavaScript được Chrome chạy qua page.evaluate().
EXTRACT_RESULTS_JS = r"""() => {
  const main = document.querySelector('[role="main"]');
  if (!main) return {links: [], end: false};
  const links = [...main.querySelectorAll('a[href]')].filter(a =>
    a.getClientRects().length && a.innerText.trim() &&
    !a.closest('[role="navigation"], [role="button"]') &&
    (a.getAttribute('role') === 'presentation' || a.closest('h2, h3, h4, [role="heading"]'))
  ).map(a => ({href: a.href, name: a.innerText.trim()}));
  return {links, end: /Không có kết quả|Không tìm thấy kết quả|No results found|No more results/i.test(main.innerText)};
}"""

# Chờ liên kết mới xuất hiện sau khi cuộn, dùng cùng bộ đọc để không lệch selector.
WAIT_RESULTS_JS = "previous => { const snapshot = (" + EXTRACT_RESULTS_JS + ")(); " + \
    "const seen = new Set(previous); return snapshot.end || snapshot.links.some(link => !seen.has(link.href)); }"

# Cuộn vùng chứa kết quả; hỗ trợ cả giao diện có thanh cuộn riêng và cuộn toàn trang.
SCROLL_RESULTS_JS = r"""() => {
  const main = document.querySelector('[role="main"]');
  let node = main?.querySelector('a[role="presentation"]') || main;
  while (node && node !== document.body) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight + 40) {
      node.scrollTop += Math.max(1200, node.clientHeight * 1.5);
      return;
    }
    node = node.parentElement;
  }
  window.scrollBy(0, 2000);
}"""

UI_NAMES = {"theo dõi", "follow", "thêm bạn bè", "add friend", "tham gia", "join",
            "tham gia nhóm", "join group", "xem trang cá nhân", "view profile", "xem nhóm", "view group"}


# Tạo URL tìm kiếm đúng loại và giữ nguyên từ khóa có dấu/khoảng trắng trong tham số q.
def search_url(keyword, kind):
    """Chọn đúng trang tìm kiếm và mã hóa từ khóa có dấu/khoảng trắng."""
    routes = {
        "profile": "people",
        "group": "groups",
    }
    route = routes[kind]
    query_parameters = {"q": keyword}
    query_string = urlencode(query_parameters)
    return f"https://www.facebook.com/search/{route}/?{query_string}"


# Chuẩn hóa URL, lọc sai loại và loại liên kết trùng trong cùng lượt đọc DOM.
def normalize_results(links, kind):
    """Làm sạch tên/URL và bỏ những kết quả không phù hợp hoặc bị trùng."""
    results = []
    seen_urls = set()

    for link in links:
        original_name = link.get("name", "")
        name = re.sub(r"[\u200b-\u200d\ufeff]", "", original_name)
        name = " ".join(name.split())

        url = canonical_entity_url(link.get("href", ""), kind)
        if not url or not name:
            continue

        normalized_name = name.casefold()
        normalized_url = url.casefold()

        if normalized_name in UI_NAMES:
            continue
        if normalized_url in seen_urls:
            continue

        seen_urls.add(normalized_url)
        results.append({"name": name, "url": url})

    return results


# Đọc nhiều lượt kết quả tìm kiếm; yield mỗi URL một lần và dừng khi đạt giới hạn/hết kết quả.
async def iter_keyword_results(page, keyword, kind, max_results=20, max_scrolls=30, max_idle=4):
    """Yield từng kết quả tìm được; dừng khi đủ số lượng hoặc cuộn không có kết quả mới."""
    search_page_url = search_url(keyword, kind)
    print(f"==> Tìm {kind}: {keyword}\n  URL: {search_page_url}", flush=True)

    response = await page.goto(search_page_url, wait_until="domcontentloaded", timeout=30000)
    if response and response.status >= 400:
        raise RuntimeError(f"Không truy cập được tìm kiếm: HTTP {response.status}")

    current_url = urlparse(page.url)
    expected_url = urlparse(search_page_url)
    current_parameters = parse_qs(current_url.query)

    if "/login" in current_url.path or "/checkpoint" in current_url.path:
        raise RuntimeError("Facebook yêu cầu đăng nhập/xác minh; hãy xử lý trên Chrome rồi chạy lại.")

    wrong_route = current_url.path.rstrip("/") != expected_url.path.rstrip("/")
    wrong_keyword = current_parameters.get("q") != [keyword]
    if wrong_route or wrong_keyword:
        raise RuntimeError(f"Facebook chuyển sang URL khác: {page.url}")

    main_content = page.locator('[role="main"]').first
    await main_content.wait_for(state="visible", timeout=12000)
    await asyncio.sleep(2)

    seen_urls = set()
    idle_turns = 0

    # Lượt đầu đọc trang hiện có; các lượt sau tương ứng với thao tác cuộn.
    for turn in range(max_scrolls + 1):
        current_path = urlparse(page.url).path
        if "/login" in current_path or "/checkpoint" in current_path:
            raise RuntimeError("Facebook yêu cầu đăng nhập/xác minh khi tải thêm kết quả.")

        snapshot = await page.evaluate(EXTRACT_RESULTS_JS)
        results = normalize_results(snapshot["links"], kind)
        new_result_count = 0

        for result in results:
            identity = result["url"].casefold()
            if identity in seen_urls:
                continue

            seen_urls.add(identity)
            new_result_count += 1

            result_record = result.copy()
            result_record["keyword"] = keyword
            result_record["entity_type"] = kind
            result_record["search_url"] = search_page_url
            result_record["found_at"] = datetime.now(timezone.utc).isoformat()

            # main() nhận kết quả này và ghi SQLite trước khi vòng lặp đọc tiếp.
            yield result_record

            if max_results and len(seen_urls) >= max_results:
                print(f"  Đã đủ {len(seen_urls)} kết quả {kind}.", flush=True)
                return

        if new_result_count > 0:
            idle_turns = 0
        else:
            idle_turns += 1

        print(
            f"  Lượt tìm {turn + 1}: thêm {new_result_count}, tổng {len(seen_urls)} URL {kind}.",
            flush=True,
        )
        if snapshot["end"] or idle_turns >= max_idle or turn == max_scrolls:
            break

        await page.evaluate(SCROLL_RESULTS_JS)

        previous_links = []
        for link in snapshot["links"]:
            previous_links.append(link["href"])

        try:
            await page.wait_for_function(
                WAIT_RESULTS_JS,
                arg=previous_links,
                timeout=6000,
                polling=300,
            )
        except PlaywrightTimeoutError:
            # Hết thời gian chờ vẫn đọc lại một lượt để xác nhận có dữ liệu mới không.
            pass

        await asyncio.sleep(1.5)

    print(f"  Kết thúc tìm kiếm: {len(seen_urls)} kết quả {kind}.", flush=True)
