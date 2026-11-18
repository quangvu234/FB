"""Đọc trang chính và mục Giới thiệu trong một tab Chrome."""
import asyncio
import re
from urllib.parse import parse_qs, urlparse

from fb_scraper.entities.parser import parse_entity
from fb_scraper.common.urls import canonical_entity_url, entity_about_url, is_login_url


# Chỉ đọc vùng chính; loại bài viết/bình luận để chúng không lẫn vào thông tin giới thiệu.
# Đây là JavaScript đọc HTML; read_snapshot() nhận kết quả và chuyển sang các hàm Python.
EXTRACT_ENTITY_JS = r"""() => {
  const main = document.querySelector('[role="main"]');
  const visible = el => el.getClientRects().length > 0;
  let text = main ? main.innerText : '';
  const feed = main?.querySelector('[role="feed"], [role="article"]');
  if (feed?.innerText && text.includes(feed.innerText)) text = text.slice(0, text.indexOf(feed.innerText));
  return {
    text,
    headings: main ? [...main.querySelectorAll('h1, h2, h3')]
      .filter(el => visible(el) && !el.closest('[role="article"], [role="feed"]'))
      .map(el => el.innerText.trim()) : [],
    name: main ? [...main.querySelectorAll('h1')]
      .find(el => visible(el) && !el.closest('[role="article"], [role="feed"]'))?.innerText.trim() || '' : '',
    unavailable: /Bạn hiện không xem được nội dung này|This content isn't available|This content is not available|Nội dung này hiện không có sẵn/i.test(document.body.innerText),
    login_required: !main && /Đăng nhập|Log in/i.test(document.body.innerText),
  };
}"""


# Chờ vùng chính sau chuyển trang; không phụ thuộc h1 vì một số profile không có h1.
async def read_snapshot(page, url):
    """Mở URL và đọc một bản chụp dữ liệu DOM, không phải ảnh chụp màn hình."""
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    try:
        main_content = page.locator('[role="main"]').first
        await main_content.wait_for(state="visible", timeout=12000)
    except Exception:
        # Vẫn đọc DOM để nhận biết trang đăng nhập hoặc nội dung không có sẵn.
        pass

    await asyncio.sleep(3)
    snapshot = await page.evaluate(EXTRACT_ENTITY_JS)

    requested_url = urlparse(url)
    requested_parameters = parse_qs(requested_url.query)
    is_about_page = False
    if "/about" in requested_url.path:
        is_about_page = True
    if requested_parameters.get("sk") == ["about"]:
        is_about_page = True
    snapshot["about_page"] = is_about_page

    if is_login_url(page.url):
        snapshot["login_required"] = True
    if response and response.status >= 400:
        snapshot["unavailable"] = True

    return snapshot


# Đọc trang chính và Giới thiệu trong cùng tab; không bấm theo dõi/tham gia nhóm.
async def scrape_entity(page, url, kind):
    """Đọc trang chính, trang Giới thiệu và các tab thông tin đang còn thiếu."""
    base_url = canonical_entity_url(url, kind)
    if not base_url:
        raise ValueError(f"URL {kind} không hợp lệ: {url}")

    first_snapshot = await read_snapshot(page, base_url)
    resolved_url = canonical_entity_url(page.url, kind)
    if not resolved_url:
        resolved_url = base_url

    if first_snapshot.get("unavailable") or first_snapshot.get("login_required"):
        return parse_entity(resolved_url, kind, [first_snapshot], source_url=url)

    snapshots = [first_snapshot]
    partial = False

    try:
        about_url = entity_about_url(resolved_url, kind)
        about_snapshot = await read_snapshot(page, about_url)
        snapshots.append(about_snapshot)

        can_read_profile_tabs = kind == "profile"
        if about_snapshot.get("login_required") or about_snapshot.get("unavailable"):
            can_read_profile_tabs = False

        if can_read_profile_tabs:
            tabs_to_read = (
                (("work",), r"^(?:Công việc|Work|Công việc và học vấn|Work and education)$"),
                (("education",), r"^(?:Trình độ học vấn|Học vấn|Education|Công việc và học vấn|Work and education)$"),
                (("current_city", "hometown"), r"^(?:Thông tin cá nhân|Personal details|Nơi từng sống|Places lived)$"),
            )

            for fields, label_pattern in tabs_to_read:
                record = parse_entity(resolved_url, kind, snapshots)
                all_fields_found = True

                for field in fields:
                    if record.get(field) is None:
                        all_fields_found = False
                        break

                if all_fields_found:
                    continue

                tab_selector = '[role="tab"], [role="button"], a'
                label_regex = re.compile(label_pattern, re.I)
                controls = page.locator(tab_selector).filter(has_text=label_regex)
                control_count = await controls.count()
                maximum_controls = min(control_count, 5)

                for index in range(maximum_controls):
                    control = controls.nth(index)
                    if await control.is_visible():
                        await control.click(timeout=3000)
                        await asyncio.sleep(3)
                        snapshot = await page.evaluate(EXTRACT_ENTITY_JS)
                        snapshot["about_page"] = True
                        snapshots.append(snapshot)
                        break

    except Exception as error:
        print(
            f"  Chưa đọc được mục Giới thiệu ({type(error).__name__}); giữ thông tin từ trang chính.",
            flush=True,
        )
        partial = True

    return parse_entity(resolved_url, kind, snapshots, source_url=url, partial=partial)
