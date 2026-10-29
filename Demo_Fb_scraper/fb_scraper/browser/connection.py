"""Kết nối trình duyệt và kiểm tra đúng hồ sơ trước khi thu thập."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright

from fb_scraper.browser.settings import (
    chrome_user_data_dir, connection_help, get_cdp_url,
    profile_directory, use_local_browser, use_system_chrome,
)
from fb_scraper.browser.launcher import ensure_local_chrome, open_chrome

PROFILE_PATH_JS = "() => document.getElementById('profile_path')?.textContent.trim() || ''"


async def verify_profile(page):
    """Đọc đường dẫn ở chrome://version rồi so với hồ sơ mà project yêu cầu."""
    expected_path = chrome_user_data_dir() / profile_directory()
    expected_path = expected_path.resolve()
    actual_path_text = ""

    # Trang chrome://version có thể cần một khoảng ngắn để hiển thị thông tin.
    for attempt in range(30):
        actual_path_text = await page.evaluate(PROFILE_PATH_JS)
        if actual_path_text:
            break
        await asyncio.sleep(0.1)

    profile_matches = False
    if actual_path_text:
        actual_path = Path(actual_path_text).resolve()
        profile_matches = actual_path == expected_path

    if not profile_matches:
        displayed_path = actual_path_text
        if not displayed_path:
            displayed_path = "không xác định"

        message = (
            f"Chrome kết nối không dùng hồ sơ yêu cầu: {expected_path}. "
            f"Hồ sơ thực tế: {displayed_path}. " + connection_help()
        )
        raise RuntimeError(message)


@asynccontextmanager
async def browser_context():
    """Cấp context Chrome cho phần thu thập.

    Code trước yield: kết nối và kiểm tra hồ sơ.
    Code sau yield: rời kết nối Playwright, giữ Chrome của người dùng đang mở.
    """
    async with async_playwright() as playwright:
        if use_local_browser():
            # Việc mở Chrome có chờ đợi. to_thread giúp không chặn các tác vụ async khác.
            endpoint = await asyncio.to_thread(ensure_local_chrome)
        else:
            endpoint = get_cdp_url()

        try:
            browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=120000)
        except Exception as error:
            if use_system_chrome() or use_local_browser():
                help_text = connection_help()
            else:
                help_text = "Kiểm tra BROWSER_CDP_URL và Chrome CDP đang mở."

            raise RuntimeError("Không kết nối được Chrome. " + help_text) from error

        if not browser.contexts:
            raise RuntimeError("Chrome không có browser context có thể sử dụng.")

        context = browser.contexts[0]
        if use_system_chrome() or use_local_browser():
            diagnostic_page = await context.new_page()
            try:
                await diagnostic_page.goto("chrome://version", wait_until="domcontentloaded")
                await verify_profile(diagnostic_page)
            finally:
                await diagnostic_page.close()

        # Bên gọi nhận context ở dòng: async with browser_context() as context.
        yield context
        # Khi rời async with, Playwright ngắt kết nối; không đóng Chrome/context của người dùng.
        # Do not call browser.close()/context.close() on the user's Chrome.


def create_agent_browser(browser_class):
    """Cùng thứ tự cấu hình với collector; không tự fallback sang phiên trắng."""
    # All modes connect over CDP. browser-use never clones or replaces our profile.
    return browser_class(cdp_url=get_cdp_url(), keep_alive=True)


async def start_agent_browser(browser):
    if use_local_browser():
        await asyncio.to_thread(ensure_local_chrome)
    await browser.start()
    if use_system_chrome() or use_local_browser():
        probe = await browser.new_page("chrome://version")
        try:
            await verify_profile(probe)
        finally:
            await browser.close_page(probe)


def run_cli(argv=None):
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Mở Chrome theo cùng cấu hình .env của collector.")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    if not args.open:
        parser.print_help()
    else:
        try:
            open_chrome()
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(1, f"LỖI: {exc}\n")


if __name__ == "__main__":
    run_cli()
