"""HTTP server cục bộ cho giao diện, không cần cài thêm framework."""
import argparse
import asyncio
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import time
import threading
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import ValidationError

from fb_scraper.web import data
from fb_scraper.web.jobs import JobManager
from fb_scraper.web.sources import RunRequest, build_plan

STATIC = Path(__file__).parent / "static"
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/comments.js": ("comments.js", "text/javascript"), "/styles.css": ("styles.css", "text/css"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager=None):
        super().__init__(address, Handler)
        self.manager = manager or JobManager()
        self.token = secrets.token_urlsafe(32)
        self.browser_cache = (0, False)

    def browser_ready(self):
        checked, ready = self.browser_cache
        if time.monotonic() - checked < 5:
            return ready
        from fb_scraper.browser.launcher import _debugging_ready
        from fb_scraper.browser.settings import get_cdp_url
        try:
            endpoint = get_cdp_url()
            parsed = urlparse(endpoint)
            if parsed.scheme in {"ws", "wss"}:
                with socket.create_connection((parsed.hostname, parsed.port), timeout=0.4):
                    ready = True
            else:
                ready = _debugging_ready(endpoint)
        except (OSError, ValueError, RuntimeError):
            ready = False
        self.browser_cache = (time.monotonic(), ready)
        return ready


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def respond(self, payload, status=200, content_type="application/json"):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if content_type == "application/json" else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return self.respond({"error": "Host không hợp lệ."}, 403)
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ASSETS:
                filename, mime = ASSETS[path]
                return self.respond((STATIC / filename).read_bytes(), content_type=mime)
            if path == "/api/state":
                return self.respond({**self.server.manager.snapshot(), "stats": data.summary(),
                                     "browser_ready": self.server.browser_ready(), "token": self.server.token})
            if path == "/api/posts":
                params = parse_qs(parsed.query)
                offset = max(0, min(int(params.get("offset", ["0"])[0]), 1000000))
                limit = max(1, min(int(params.get("limit", ["12"])[0]), 100))
                return self.respond(data.list_posts(params.get("q", [""])[0][:500], offset, limit))
            if path.startswith("/api/posts/"):
                post = data.get_post(unquote(path[len("/api/posts/"):]))
                return self.respond(post if post else {"error": "Không tìm thấy bài viết."}, 200 if post else 404)
            if path == "/api/export":
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="posts.jsonl"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                for line in data.export_lines():
                    self.wfile.write(line.encode("utf-8"))
                return
            return self.respond({"error": "Không tìm thấy đường dẫn."}, 404)
        except (ValueError, OSError) as error:
            return self.respond({"error": str(error)}, 400)
        except Exception as error:
            return self.respond({"error": f"Chưa đọc được dữ liệu: {error}"}, 503)

    def do_POST(self):
        if not self.valid_host():
            return self.respond({"error": "Host không hợp lệ."}, 403)
        expected_origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        token = self.headers.get("X-Scraper-Token", "")
        if (origin is not None and origin not in expected_origins) or not hmac.compare_digest(token, self.server.token):
            return self.respond({"error": "Phiên giao diện hết hạn. Hãy tải lại trang."}, 403)
        if self.headers.get_content_type() != "application/json":
            return self.respond({"error": "Yêu cầu phải là JSON."}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                return self.respond({"error": "Đầu vào quá lớn hoặc rỗng."}, 400)
            payload = json.loads(self.rfile.read(length))
            if self.path == "/api/run":
                request = RunRequest.model_validate(payload)
                plan = build_plan(request)
                config = {"plan": plan, "options": {"max_posts": request.max_posts,
                          "max_comments": request.max_comments, "ocr": request.ocr}}
                return self.respond({"job_id": self.server.manager.start(config)}, 202)
            if self.path == "/api/stop":
                return self.respond({"stopping": self.server.manager.stop()})
            if self.path == "/api/browser":
                return self.respond({"job_id": self.server.manager.start({"action": "browser"})}, 202)
            return self.respond({"error": "Không tìm thấy thao tác."}, 404)
        except ValidationError as error:
            return self.respond({"error": "Dữ liệu không hợp lệ. Kiểm tra nguồn, số bài (1–500) và bình luận (0–5000).",
                                 "details": error.errors(include_context=False, include_input=False)}, 400)
        except (ValueError, TypeError) as error:
            return self.respond({"error": str(error)}, 400)
        except RuntimeError as error:
            return self.respond({"error": str(error)}, 409)
        except Exception as error:
            return self.respond({"error": f"Chưa khởi động được: {error}"}, 500)


def open_startup_tabs(url):
    try:
        from fb_scraper.browser.workspace import open_workspace
        asyncio.run(open_workspace(url))
    except Exception as error:
        print(f"Chưa tự mở được Chrome: {error}\nBạn có thể mở giao diện tại {url}.", flush=True)


def run_cli(argv=None):
    parser = argparse.ArgumentParser(description="Mở giao diện thu thập Facebook trên máy này.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="tự mở giao diện và Facebook trong Chrome của project")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Cổng phải nằm trong khoảng 1–65535.")
    from fb_scraper.storage.database import init_db
    database = init_db()
    database.close()
    try:
        server = AppServer(("127.0.0.1", args.port))
    except OSError as error:
        parser.exit(1, f"Không mở được giao diện: {error}. Thử --port khác.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Giao diện thu thập: {url}\nGiữ terminal này mở. Nhấn Ctrl+C để tắt giao diện.", flush=True)
    if args.open:
        # Server phục vụ ngay để tab giao diện có thể tải trong lúc Chrome kết nối.
        threading.Thread(target=open_startup_tabs, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang đóng giao diện…", flush=True)
    finally:
        server.manager.close()
        server.server_close()
