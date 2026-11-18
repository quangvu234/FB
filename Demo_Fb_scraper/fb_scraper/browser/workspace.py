"""Mở Facebook và giao diện trong đúng hồ sơ Chrome dùng cho collector."""
from urllib.parse import urlparse

from fb_scraper.browser.connection import browser_context
from fb_scraper.common.urls import FACEBOOK_HOSTS


def same_ui_url(actual, expected):
    actual_url, expected_url = urlparse(actual), urlparse(expected)
    return (actual_url.scheme, actual_url.netloc, actual_url.path.rstrip("/")) == (
        expected_url.scheme, expected_url.netloc, expected_url.path.rstrip("/"))


async def open_workspace(url):
    """Dùng lại tab đã có; giữ cả hai tab và Chrome khi ngắt kết nối điều khiển."""
    async with browser_context() as context:
        facebook = next((page for page in context.pages if urlparse(page.url).hostname in FACEBOOK_HOSTS), None)
        if facebook is None:
            facebook = await context.new_page()
            try:
                await facebook.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
            except Exception as error:
                print(f"Facebook chưa tải xong ({type(error).__name__}); có thể đăng nhập trong tab Chrome.", flush=True)

        ui = next((page for page in context.pages if same_ui_url(page.url, url)), None)
        if ui is None:
            ui = await context.new_page()
            await ui.goto(url, wait_until="domcontentloaded", timeout=15000)
        await ui.bring_to_front()
        print("Đã mở giao diện và Facebook trong cùng hồ sơ Chrome của project.", flush=True)
