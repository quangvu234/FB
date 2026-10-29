"""Hồi quy lỗi nhận nhầm search/posts là permalink và mở tab bình luận lỗi."""
import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fb_scraper.posts import parser as posts
from fb_scraper.posts import comments as comments
from fb_scraper.common.urls import POST_URL_JS, canonical_post_url


URL_CASES = [
    ("https://www.facebook.com/search/posts?q=messi", ""),
    ("https://www.facebook.com/search/posts", ""),
    ("https://www.facebook.com/search/posts?q=pfbidFake&story_fbid=123", ""),
    ("https://example.com/user/posts/123", ""),
    ("https://www.facebook.com.evil.test/user/posts/123", ""),
    ("https://www.facebook.com/user/posts", ""),
    ("https://www.facebook.com/user/photos", ""),
    ("https://www.facebook.com/photo.php", ""),
    ("https://www.facebook.com/watch", ""),
    ("javascript:alert('pfbidFake')", ""),
    ("https://www.facebook.com/user/posts/pfbidAb123?__cft__=tracking", "https://www.facebook.com/user/posts/pfbidAb123"),
    ("https://m.facebook.com/groups/111/posts/222/?__tn__=tracking", "https://www.facebook.com/groups/111/posts/222/"),
    ("/user/posts/123?__tn__=tracking", "https://www.facebook.com/user/posts/123"),
    ("https://www.facebook.com/permalink.php?story_fbid=123&id=456&__tn__=tracking", "https://www.facebook.com/permalink.php?story_fbid=123&id=456"),
    ("https://www.facebook.com/story.php?story_fbid=pfbidABC&id=456", "https://www.facebook.com/story.php?story_fbid=pfbidABC&id=456"),
    ("https://www.facebook.com/photo/?fbid=123&set=a.456&__tn__=tracking", "https://www.facebook.com/photo/?fbid=123&set=a.456"),
    ("https://www.facebook.com/user/photos/a.111/222/?__tn__=tracking", "https://www.facebook.com/user/photos/a.111/222/"),
    ("https://www.facebook.com/watch/?v=123&__tn__=tracking", "https://www.facebook.com/watch/?v=123"),
    ("https://www.facebook.com/user/videos/123/", "https://www.facebook.com/user/videos/123/"),
    ("https://www.facebook.com/reel/123", "https://www.facebook.com/reel/123"),
    ("https://www.facebook.com/share/p/AbCd123/", "https://www.facebook.com/share/p/AbCd123/"),
]


class PostURLTests(unittest.IsolatedAsyncioTestCase):
    def test_relative_time_accepts_english_hours_suffix(self):
        earliest = datetime.now(timezone.utc) - timedelta(hours=3)
        result = posts.parse_relative_time("3 hrs")
        latest = datetime.now(timezone.utc) - timedelta(hours=3)
        parsed_time = datetime.fromisoformat(result)
        self.assertLessEqual(earliest, parsed_time)
        self.assertLessEqual(parsed_time, latest)

    def test_reject_navigation_and_preserve_identifying_parameters(self):
        for href, expected in URL_CASES:
            with self.subTest(href=href):
                self.assertEqual(canonical_post_url(href), expected)

    def test_dom_predicate_agrees_with_python(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node chưa có; bỏ qua thực thi predicate JavaScript.")
        script = (
            "const predicate = " + POST_URL_JS + ";"
            "const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "process.stdout.write(JSON.stringify(cases.map(url => predicate(url))));"
        )
        result = subprocess.run(
            [node, "-e", script], input=json.dumps([url for url, _ in URL_CASES]),
            text=True, capture_output=True, check=True, timeout=15,
        )
        self.assertEqual(json.loads(result.stdout), [bool(expected) for _, expected in URL_CASES])

    def test_article_selects_permalink_after_search_and_photo_links(self):
        permalink = {"href": "https://www.facebook.com/page/posts/123?__tn__=tracking", "text": "2 giờ"}
        raw = {
            "text": "Một bài viết đủ dài để kiểm tra thu thập dữ liệu.", "author": "Page", "imgs": [],
            "links": [
                {"href": "https://www.facebook.com/search/posts?q=messi", "text": "Bài viết"},
                {"href": "https://www.facebook.com/photo.php?fbid=456", "text": ""},
                permalink,
            ],
        }
        post = posts.parse_article(raw, "kw:messi")
        self.assertEqual(post["url"], "https://www.facebook.com/page/posts/123")
        self.assertEqual(post["post_id"], "123")
        self.assertEqual(post["posted_raw"], "2 giờ")

    def test_article_without_permalink_still_preserves_text(self):
        raw = {
            "text": "Một bài viết đủ dài nhưng chưa thấy permalink.", "author": "Page", "imgs": [],
            "links": [{"href": "https://www.facebook.com/search/posts?q=messi", "text": "Bài viết"}],
        }
        post = posts.parse_article(raw, "kw:messi")
        self.assertEqual(post["url"], "")
        self.assertEqual(post["text"], raw["text"])
        self.assertTrue(post["post_id"].startswith("h_"))

    async def test_invalid_comment_url_never_opens_a_tab(self):
        context = SimpleNamespace(new_page=AsyncMock())
        for href in ("https://www.facebook.com/search/posts?q=messi", "https://www.facebook.com/search/posts", ""):
            self.assertEqual(await comments.scrape_top_comments(context, href, 3), [])
        context.new_page.assert_not_awaited()

    async def test_comment_tab_keeps_story_id_and_closes(self):
        page = SimpleNamespace(url="https://www.facebook.com/permalink.php?story_fbid=123&id=456", goto=AsyncMock(), close=AsyncMock(), evaluate=AsyncMock(return_value=[]))
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        href = "https://www.facebook.com/permalink.php?story_fbid=123&id=456&__tn__=tracking"
        with patch.object(comments, "human_pause", new=AsyncMock()), \
             patch.object(comments, "expand_see_more", new=AsyncMock()), \
             patch.object(comments, "load_more_comments", new=AsyncMock(return_value=False)):
            self.assertEqual(await comments.scrape_top_comments(context, href, 3), [])
        page.goto.assert_awaited_once_with(
            "https://www.facebook.com/permalink.php?story_fbid=123&id=456", wait_until="domcontentloaded", timeout=30000
        )
        page.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
