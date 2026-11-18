"""Kiểm tra giao diện thật bằng Chrome headless; dữ liệu tạm và worker giả."""
import threading
import unittest

from playwright.sync_api import sync_playwright, expect

from fb_scraper.browser.launcher import find_chrome
from fb_scraper.storage import database as storage
from fb_scraper.web.server import AppServer
from tests.persistence_fixtures import PersistenceFixture
from tests.test_web import FakeJobs


class WebUITests(PersistenceFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            executable = find_chrome()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(executable_path=str(executable), headless=True)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        from unittest.mock import patch
        super().setUp()
        self.jobs = FakeJobs()
        self.enterContext(patch.object(AppServer, "browser_ready", return_value=False))
        self.server = AppServer(("127.0.0.1", 0), self.jobs)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 1100})
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def open(self):
        self.page.goto(f"http://127.0.0.1:{self.server.server_port}")
        expect(self.page.locator("#browser-state")).to_have_text("Chrome chưa được mở")

    def test_enter_mixed_sources_start_and_stop(self):
        self.open()
        expect(self.page.locator("#start-button")).to_be_disabled()
        self.page.locator("#sources").fill("việc làm\nhttps://www.facebook.com/groups/123")
        expect(self.page.locator("#source-count")).to_have_text("2 nguồn")
        self.page.locator("#max-posts").fill("3")
        self.page.locator("#max-comments").fill("2")
        self.page.locator("#start-button").click()
        expect(self.page.locator("#job-badge")).to_have_text("Đang thu thập")
        self.assertEqual(self.jobs.configs[0]["options"]["max_posts"], 3)
        self.assertEqual([source["kind"] for source in self.jobs.configs[0]["plan"]], ["keyword", "group"])
        self.page.locator("#stop-button").click()
        expect(self.page.locator("#job-badge")).to_have_text("Đã dừng")
        self.assertEqual(self.errors, [])

    def test_page_mode_and_invalid_url_feedback(self):
        self.open()
        self.page.get_by_text("Trang", exact=True).click()
        self.page.locator("#sources").fill("https://example.org")
        self.page.locator("#start-button").click()
        expect(self.page.locator("#form-error")).to_be_visible()
        self.assertEqual(self.jobs.configs, [])
        self.page.locator("#sources").fill("https://www.facebook.com/example.page")
        self.page.locator("#start-button").click()
        expect(self.page.locator("#job-badge")).to_have_text("Đang thu thập")
        self.assertEqual(self.jobs.configs[0]["plan"][0]["mode"], "page")
        self.assertEqual(self.jobs.configs[0]["plan"][0]["kind"], "profile")

    def test_post_detail_reply_tree_and_html_is_rendered_as_text(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        storage.save_post(db, {"post_id": "1", "author": "Tác giả mẫu", "text": '<img src=x onerror="window.injected=true">',
                              "top_comments": [
                                  {"comment_id": "10", "text": "Bình luận gốc", "is_reply": False},
                                  {"comment_id": "11", "text": "Reply cấp 1", "parent_comment_id": "10", "root_comment_id": "10"},
                                  {"comment_id": "12", "text": "Reply cấp 2", "parent_comment_id": "11", "root_comment_id": "10"},
                                  {"comment_id": "13", "text": "Chưa biết cha", "is_reply": True, "root_comment_id": "10"}]})
        self.open()
        self.page.locator(".post-row").click()
        expect(self.page.locator("#post-dialog")).to_be_visible()
        expect(self.page.locator('[data-comment-id="12"]')).to_have_attribute("data-depth", "2")
        expect(self.page.locator('[data-comment-id="13"]')).to_contain_text("chưa rõ cha trực tiếp")
        self.assertIsNone(self.page.evaluate("window.injected"))
        self.assertEqual(self.page.locator("#post-detail img").count(), 0)
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#post-dialog")).not_to_be_visible()
        self.assertEqual(self.errors, [])

    def test_small_screen_has_no_horizontal_overflow(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open()
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        expect(self.page.locator("#sources")).to_be_visible()
        expect(self.page.locator("#open-browser-mobile")).to_be_visible()
        self.page.locator("#open-browser-mobile").click()
        expect(self.page.locator("#job-badge")).to_have_text("Đang mở Chrome")
        self.assertEqual(self.jobs.configs[0]["action"], "browser")
        self.assertEqual(self.errors, [])

    def test_result_list_shows_entire_long_post_without_line_clamp(self):
        db = storage.init_db()
        self.addCleanup(db.close)
        text = '\n'.join(f'Dòng nội dung đầy đủ số {index}' for index in range(30))
        storage.save_post(db, {"post_id": "1", "author": "Tác giả", "text": text})
        self.open()
        excerpt = self.page.locator('.post-excerpt')
        expect(excerpt).to_have_text(text)
        self.assertEqual(excerpt.evaluate('el => getComputedStyle(el).webkitLineClamp'), 'none')
        self.assertTrue(excerpt.evaluate('el => el.clientHeight >= el.scrollHeight'))


if __name__ == "__main__":
    unittest.main()
