"""Thao tác dùng chung trên một tab Facebook: chờ ngẫu nhiên và mở nội dung bị thu gọn."""
import asyncio
import random

from playwright.async_api import Page

from fb_scraper.common.content import EXPAND_LABEL_RE, EXPAND_LABEL_SOURCE


async def human_pause(a=1.5, b=4.0):
    """Chờ ngẫu nhiên từ a đến b giây giữa các thao tác, không chặn vòng lặp asyncio."""
    await asyncio.sleep(random.uniform(a, b))


async def expand_see_more(page: Page):
    """Mở các đoạn bị thu gọn, kể cả span/button/a và DOM thay đổi sau mỗi lần bấm."""
    clicked = 0
    for _round in range(5):
        # Chụp handle để việc nút bị xóa không làm nth(index) bỏ qua nút kế tiếp.
        buttons = await page.get_by_text(EXPAND_LABEL_RE).element_handles()
        expanded = 0
        for button in buttons:
            try:
                in_content = await button.evaluate("""el =>
                    !document.querySelector('[role="main"], [role="dialog"]') ||
                    Boolean(el.closest('[role="main"], [role="dialog"]'))""")
                if not in_content or not await button.is_visible():
                    continue
                await button.click(timeout=1500)
                clicked += 1
                expanded += 1
                try:
                    await page.wait_for_function(
                        "([el, pattern]) => !el.isConnected || el.getAttribute('aria-expanded') === 'true' || "
                        "!new RegExp(pattern, 'i').test(el.innerText || el.textContent || '')",
                        arg=[button, EXPAND_LABEL_SOURCE], timeout=1200,
                    )
                except Exception:
                    pass
            except Exception:
                # Nút có thể vừa biến mất do một nút khác mở toàn bộ đoạn văn.
                continue
        if not expanded:
            break
    return clicked
