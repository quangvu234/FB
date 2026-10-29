"""Đọc cấu hình hồ sơ Chrome và xác định endpoint CDP."""
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from fb_scraper.common.paths import PROJECT_ROOT

DEFAULT_CDP_URL = "http://localhost:9222"
LOCAL_CDP_URL = "http://127.0.0.1:9223"

for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT / ".venv" / ".env"):
    load_dotenv(env_path, override=False)


def use_system_chrome():
    """Trả về True khi người dùng chọn Chrome cá nhân đang mở."""
    setting = os.getenv("USE_SYSTEM_CHROME", "0")
    normalized_setting = setting.strip().lower()
    return normalized_setting in {"1", "true", "yes"}


def use_local_browser():
    """Chrome cá nhân được ưu tiên; nếu không, kiểm tra chế độ hồ sơ riêng."""
    if use_system_chrome():
        return False

    setting = os.getenv("USE_LOCAL_BROWSER", "0")
    normalized_setting = setting.strip().lower()
    return normalized_setting in {"1", "true", "yes"}


def profile_directory():
    """Đọc tên thư mục con: Default cho hồ sơ riêng, Profile 2 cho Chrome cá nhân."""
    default_profile = "Profile 2"
    if use_local_browser():
        default_profile = "Default"

    profile = os.getenv("CHROME_PROFILE_DIRECTORY", default_profile)
    profile = profile.strip()

    if not profile or profile in {".", ".."}:
        raise ValueError("CHROME_PROFILE_DIRECTORY phải là tên thư mục hồ sơ, ví dụ Profile 2.")

    for character in '/\\:"':
        if character in profile:
            raise ValueError("CHROME_PROFILE_DIRECTORY phải là tên thư mục hồ sơ, ví dụ Profile 2.")

    return profile


def chrome_user_data_dir():
    """Đường dẫn tương đối tính từ thư mục có main.py, không phụ thuộc terminal."""
    configured_path = os.getenv("CHROME_USER_DATA_DIR")

    if configured_path:
        expanded_path = os.path.expandvars(configured_path)
        user_data_path = Path(expanded_path).expanduser()

        if not user_data_path.is_absolute():
            user_data_path = PROJECT_ROOT / user_data_path

        return user_data_path.resolve()

    if use_local_browser():
        return PROJECT_ROOT / "fb_profile"

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Google" / "Chrome" / "User Data"

    raise RuntimeError("Hãy đặt CHROME_USER_DATA_DIR đến thư mục User Data của Chrome.")


def connection_help():
    if use_local_browser():
        return (
            "Project dùng hồ sơ Chrome riêng được lưu trên ổ đĩa. "
            "Chạy scripts/open_chrome.ps1 để đăng nhập Facebook khi thiết lập ban đầu. "
            "Nếu Chrome của hồ sơ này đang mở thủ công, hãy đóng cửa sổ đó và chạy lại."
        )
    return (
        f"Mở Chrome {profile_directory()} bằng scripts/open_chrome.ps1, bật Remote debugging "
        "tại chrome://inspect/#remote-debugging, rồi chạy lại và bấm Allow khi Chrome hỏi."
    )


def get_cdp_url(default=DEFAULT_CDP_URL):
    """Chọn địa chỉ điều khiển Chrome theo chế độ đang cấu hình."""
    if use_local_browser():
        return local_cdp_url()

    if not use_system_chrome():
        configured_url = os.getenv("BROWSER_CDP_URL")
        if configured_url:
            return configured_url
        return default

    # Chrome cá nhân ghi cổng và đường dẫn WebSocket vào file này.
    endpoint_file = chrome_user_data_dir() / "DevToolsActivePort"
    try:
        file_content = endpoint_file.read_text(encoding="utf-8")
        non_empty_lines = []

        for line in file_content.splitlines():
            cleaned_line = line.strip()
            if cleaned_line:
                non_empty_lines.append(cleaned_line)

        port = int(non_empty_lines[0])
        endpoint = non_empty_lines[1]

        if port < 1 or port > 65535:
            raise ValueError("Invalid debugging endpoint")

        endpoint_pattern = r"/devtools/browser/[a-zA-Z0-9_-]+"
        if not re.fullmatch(endpoint_pattern, endpoint):
            raise ValueError("Invalid debugging endpoint")
    except (OSError, ValueError, IndexError) as error:
        message = "Không đọc được endpoint Chrome. " + connection_help()
        raise RuntimeError(message) from error

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    except OSError as error:
        message = "Endpoint Chrome không còn hoạt động. " + connection_help()
        raise RuntimeError(message) from error

    print("Đang kết nối Chrome; hãy bấm Allow khi Chrome hỏi.", flush=True)
    return f"ws://127.0.0.1:{port}{endpoint}"


def local_cdp_url():
    """Hồ sơ automation chỉ nhận địa chỉ HTTP trên chính máy này."""
    url = os.getenv("BROWSER_CDP_URL")
    if not url:
        url = LOCAL_CDP_URL

    parsed_url = urlparse(url)
    valid = True

    try:
        if parsed_url.scheme != "http":
            valid = False
        if parsed_url.hostname not in {"127.0.0.1", "localhost"}:
            valid = False

        port = parsed_url.port
        if port is None:
            valid = False
        elif port < 1 or port > 65535:
            valid = False

        if parsed_url.username is not None or parsed_url.password is not None:
            valid = False
        if parsed_url.path not in {"", "/"}:
            valid = False
        if parsed_url.query or parsed_url.fragment:
            valid = False
    except ValueError:
        valid = False

    if not valid:
        raise ValueError("Chế độ hồ sơ riêng cần BROWSER_CDP_URL dạng http://127.0.0.1:9223.")

    return url.rstrip("/")
