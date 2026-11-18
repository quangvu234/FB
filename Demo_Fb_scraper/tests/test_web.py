"""Kiểm tra phân loại nguồn, HTTP và dữ liệu mà giao diện sử dụng."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch

from fb_scraper.web.server import AppServer
from fb_scraper.web.sources import RunRequest, build_plan
from fb_scraper.storage import database as storage
from tests.persistence_fixtures import PersistenceFixture


class FakeJobs:
    def __init__(self):
        self.configs = []
        self.current = None

    def snapshot(self):
        return {"current": self.current, "history": [self.current] if self.current else []}

    def start(self, config):
        if self.current and self.current["status"] == "running":
            raise RuntimeError("Đang có một lượt chạy.")
        self.configs.append(config)
        self.current = {"id": "test-job", "status": "running", "action": config.get("action", "collect"),
                        "completed": 0, "total": len(config.get("plan", [])), "label": "Nguồn thử nghiệm",
                        "logs": ["Nhật ký thử nghiệm"], "started_at": "2026-11-18T00:00:00Z"}
        return "test-job"

    def stop(self):
        if self.current:
            self.current["status"] = "cancelled"
            return True
        return False

    def close(self):
        pass


class SourcePlanTests(unittest.TestCase):
    def test_mixed_sources_and_canonical_duplicates(self):
        plan = build_plan(RunRequest(sources="việc làm\nhttps://www.facebook.com/zuck?ref=x\n"
                                 "https://www.facebook.com/groups/123\nhttps://www.facebook.com/zuck"))
        self.assertEqual([source["kind"] for source in plan], ["keyword", "profile", "group"])
        self.assertEqual(plan[1]["value"], "https://www.facebook.com/zuck")

    def test_page_uses_profile_collector_and_bare_facebook_url_is_accepted(self):
        plan = build_plan(RunRequest(sources="www.facebook.com/page.example", mode="page"))
        self.assertEqual((plan[0]["mode"], plan[0]["kind"]), ("page", "profile"))

    def test_rejects_foreign_urls_navigation_wrong_kind_and_blank(self):
        for sources, mode in [("https://example.org", "auto"), ("https://www.facebook.com/search/posts?q=x", "auto"),
                              ("https://www.facebook.com/name", "group"), ("   ", "auto"),
                              ("https://www.facebook.com/name", "keyword")]:
            with self.subTest(sources=sources, mode=mode), self.assertRaises(ValueError):
                build_plan(RunRequest(sources=sources, mode=mode))

    def test_limits_and_no_shell_fields(self):
        for kwargs in ({"max_posts": 0}, {"max_posts": "20"}, {"max_comments": -1}, {"command": "anything"}):
            with self.assertRaises(ValueError):
                RunRequest(sources="test", **kwargs)
        with self.assertRaises(ValueError):
            build_plan(RunRequest(sources="\n".join(str(index) for index in range(51))))


class WebHTTPTests(PersistenceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.jobs = FakeJobs()
        self.enterContext(patch.object(AppServer, "browser_ready", return_value=False))
        self.server = AppServer(("127.0.0.1", 0), self.jobs)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        request_headers = {"Content-Type": "application/json", "X-Scraper-Token": self.server.token}
        request_headers.update(headers or {})
        connection.request("POST" if payload is not None else "GET", path,
                           json.dumps(payload) if payload is not None else None, request_headers)
        response = connection.getresponse()
        return response.status, response.read()

    def test_initial_empty_state_and_static_assets(self):
        status, body = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["stats"]["posts"], 0)
        self.assertFalse(storage.DB_PATH.exists())
        for path in ("/", "/styles.css", "/app.js", "/comments.js", "/favicon.svg"):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request("/../.env")[0], 404)

    def test_start_routes_mixed_sources_and_serializes_runs(self):
        payload = {"sources": "Python\nhttps://www.facebook.com/groups/123", "max_posts": 3, "max_comments": 2}
        self.assertEqual(self.request("/api/run", payload)[0], 202)
        self.assertEqual([source["kind"] for source in self.jobs.configs[0]["plan"]], ["keyword", "group"])
        self.assertEqual(self.request("/api/run", payload)[0], 409)
        self.assertEqual(self.request("/api/stop", {})[0], 200)
        self.assertEqual(self.jobs.current["status"], "cancelled")

    def test_csrf_host_and_validation_reject_before_start(self):
        payload = {"sources": "test"}
        for headers in ({"X-Scraper-Token": "wrong"}, {"Origin": "https://evil.example"}, {"Host": "evil.example"}):
            self.assertEqual(self.request("/api/run", payload, headers)[0], 403)
        self.assertEqual(self.request("/api/run", {"sources": "https://example.org"})[0], 400)
        self.assertEqual(self.request("/api/run", {"sources": "test", "max_posts": -1})[0], 400)
        self.assertEqual(self.jobs.configs, [])

    def test_posts_details_export_and_unicode_search(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        storage.save_post(db, {"post_id": "1", "author": "Người Viết", "text": "TUYỂN DỤNG",
                              "images": ["image"], "top_comments": [
                                  {"comment_id": "10", "text": "Root", "is_reply": False},
                                  {"comment_id": "11", "parent_comment_id": "10", "text": "Reply"}]})
        status, body = self.request("/api/posts?q=tuy%E1%BB%83n")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["total"], 1)
        self.assertEqual(json.loads(self.request("/api/posts/1")[1])["top_comments"][1]["parent_comment_id"], "10")
        self.assertEqual(json.loads(self.request("/api/export")[1])["post_key"], "1")
        self.assertEqual(json.loads(self.request("/api/state")[1])["stats"], {"posts": 1, "comments": 2, "images": 1})
        self.assertEqual(self.request("/api/posts/missing")[0], 404)


if __name__ == "__main__":
    unittest.main()
