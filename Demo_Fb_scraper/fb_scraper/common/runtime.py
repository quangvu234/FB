"""Thiết lập dùng chung khi chương trình khởi động từ main.py."""
import sys

from dotenv import load_dotenv

from fb_scraper.common.paths import PROJECT_ROOT


def setup_console():
    """Cho terminal Windows in được tiếng Việt; bỏ qua nếu stream không hỗ trợ."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def load_env():
    """Nạp .env cạnh main.py, sau đó .venv/.env.

    override=False: biến môi trường của tiến trình luôn được ưu tiên hơn file .env.
    """
    for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT / ".venv" / ".env"):
        load_dotenv(env_path, override=False)
