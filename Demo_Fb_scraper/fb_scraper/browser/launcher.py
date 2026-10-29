"""Tìm Chrome, mở hồ sơ cố định và chờ cổng điều khiển sẵn sàng."""
import http.client
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from fb_scraper.browser.settings import (
    chrome_user_data_dir, connection_help, local_cdp_url,
    profile_directory, use_local_browser,
)


def find_chrome():
    """Tìm chrome.exe do người dùng chỉ định hoặc trong các thư mục cài đặt Windows."""
    configured_executable = os.getenv("CHROME_EXECUTABLE")
    candidate_paths = []

    if configured_executable:
        expanded_path = os.path.expandvars(configured_executable)
        candidate_paths.append(Path(expanded_path).expanduser())
    else:
        environment_names = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")

        for environment_name in environment_names:
            install_folder = os.getenv(environment_name)
            if not install_folder:
                continue

            executable_path = Path(install_folder) / "Google" / "Chrome" / "Application" / "chrome.exe"
            candidate_paths.append(executable_path)

    for candidate_path in candidate_paths:
        if candidate_path.is_file():
            return candidate_path

    raise RuntimeError("Không tìm thấy Google Chrome. Hãy đặt CHROME_EXECUTABLE đến chrome.exe đã cài.")


def _debugging_ready(url):
    """Hỏi Chrome về địa chỉ WebSocket; trả False nếu cổng chưa sẵn sàng."""
    parsed_url = urlparse(url)
    client = http.client.HTTPConnection(parsed_url.hostname, parsed_url.port, timeout=0.5)

    try:
        client.request("GET", "/json/version")
        response = client.getresponse()

        if response.status != 200:
            return False

        response_body = response.read(65536)
        browser_info = json.loads(response_body)
        if not isinstance(browser_info, dict):
            return False

        websocket_url = browser_info.get("webSocketDebuggerUrl")
        if not isinstance(websocket_url, str):
            return False

        return websocket_url.startswith("ws://")
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        client.close()


def _port_open(url):
    """Kiểm tra có ứng dụng nào đang nghe trên cổng, chưa khẳng định đó là Chrome."""
    parsed_url = urlparse(url)
    server_address = (parsed_url.hostname, parsed_url.port)

    try:
        with socket.create_connection(server_address, timeout=0.5):
            return True
    except OSError:
        return False


def _local_profile_path():
    """Không cho chế độ automation dùng nhầm thư mục dữ liệu Chrome cá nhân."""
    user_data_path = chrome_user_data_dir().resolve()
    local_app_data = os.getenv("LOCALAPPDATA")

    if local_app_data:
        personal_profile_path = Path(local_app_data) / "Google" / "Chrome" / "User Data"
        personal_profile_path = personal_profile_path.resolve()

        if user_data_path == personal_profile_path:
            raise ValueError("Hồ sơ automation phải dùng thư mục riêng, ví dụ CHROME_USER_DATA_DIR=fb_profile.")

    # Hàm này cũng kiểm tra tên thư mục hồ sơ có hợp lệ hay không.
    profile_directory()
    return user_data_path


def local_launch_arguments():
    """Mỗi phần tử trong danh sách là một tham số riêng truyền cho chrome.exe."""
    url = local_cdp_url()
    port = urlparse(url).port
    user_data_path = _local_profile_path()
    user_data_path.mkdir(parents=True, exist_ok=True)

    command = []
    command.append(str(find_chrome()))
    command.append(f"--user-data-dir={user_data_path}")
    command.append(f"--profile-directory={profile_directory()}")
    command.append("--no-first-run")
    command.append("--no-default-browser-check")
    command.append("--remote-debugging-address=127.0.0.1")
    command.append(f"--remote-debugging-port={port}")
    return command


def ensure_local_chrome(timeout=20):
    """Dùng lại Chrome nếu đã sẵn sàng; nếu chưa, mở Chrome rồi chờ tối đa timeout giây."""
    url = local_cdp_url()
    _local_profile_path()

    if _debugging_ready(url):
        return url

    if _port_open(url):
        raise RuntimeError("Cổng CDP đang bị ứng dụng khác sử dụng. Đổi BROWSER_CDP_URL sang cổng loopback khác.")

    command = local_launch_arguments()
    command.append("https://www.facebook.com/")
    subprocess.Popen(command)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _debugging_ready(url):
            profile_path = chrome_user_data_dir() / profile_directory()
            print(f"Chrome dùng hồ sơ riêng: {profile_path}", flush=True)
            return url

        time.sleep(0.2)

    raise RuntimeError("Chrome chưa mở được cổng CDP. " + connection_help())


def open_chrome():
    """Mở cửa sổ để người dùng thiết lập đăng nhập, theo cùng cấu hình của collector."""
    if use_local_browser():
        endpoint = local_cdp_url()
        already_running = _debugging_ready(endpoint)
        ensure_local_chrome()

        if already_running:
            command = local_launch_arguments()
            command.append("https://www.facebook.com/")
            subprocess.Popen(command)

        print("Đăng nhập Facebook trong cửa sổ này khi cần. Không cần đăng nhập Google hoặc bấm Allow.")
        return

    executable = find_chrome()
    user_data_path = chrome_user_data_dir()
    profile = profile_directory()
    profile_path = user_data_path / profile

    if not profile_path.is_dir():
        raise RuntimeError(f"Không tìm thấy hồ sơ {profile_path}; kiểm tra cấu hình trước khi mở Chrome.")

    command = [
        str(executable),
        f"--user-data-dir={user_data_path}",
        f"--profile-directory={profile}",
        "chrome://inspect/#remote-debugging",
    ]
    subprocess.Popen(command)
    print(f"Đã yêu cầu mở Chrome {profile}. Bật Remote debugging, giữ Chrome mở và chạy collector.")
