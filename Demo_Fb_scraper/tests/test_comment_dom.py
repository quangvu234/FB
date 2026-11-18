"""Kiểm tra DOM bình luận bằng Chrome headless trên HTML cục bộ, không truy cập Facebook."""
import unittest

from playwright.sync_api import sync_playwright

from fb_scraper.browser.launcher import find_chrome
from fb_scraper.posts.comment_reader import EXTRACT_COMMENTS_JS


def article(identity, text, children="", root=None, label="Comment by", author="Alice"):
    query = f"comment_id={root or identity}"
    if root:
        query += f"&reply_comment_id={identity}"
    return f'''<div role="article" aria-label="{label} {author}">
        <h3><a role="link" href="https://www.facebook.com/{author}">{author}</a></h3>
        <div dir="auto">{text}</div>
        <a href="https://www.facebook.com/page/posts/123?{query}&amp;__cft__=tracking">1 giờ</a>
        <button role="button">Trả lời</button>{children}</div>'''


class CommentDOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            chrome = find_chrome()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(executable_path=str(chrome), headless=True)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def read(self, html):
        self.page.set_content(html)
        return self.page.evaluate(EXTRACT_COMMENTS_JS)

    def test_nested_replies_have_distinct_ids_and_only_their_own_text(self):
        reply2 = article("12", "Cấp 2", root="10", label="Reply by", author="Carol")
        reply1 = article("11", "Cấp 1", reply2, root="10", label="Reply by", author="Bob")
        records = self.read(article("10", "Bình luận gốc", reply1))
        self.assertEqual([record["id"] for record in records], ["10", "11", "12"])
        self.assertEqual([record["text"] for record in records], ["Bình luận gốc", "Cấp 1", "Cấp 2"])
        self.assertEqual(records[1]["parent_comment_id"], "10")
        self.assertEqual(records[2]["parent_comment_id"], "11")
        self.assertEqual(records[2]["root_comment_id"], "10")
        self.assertEqual(records[1]["author"], "Bob")
        self.assertEqual(records[1]["author_url"], "https://www.facebook.com/Bob")
        self.assertNotIn("tracking", records[1]["url"])
        self.assertFalse(records[0]["is_reply"])

    def test_flattened_reply_url_identifies_thread_but_does_not_invent_parent(self):
        records = self.read(article("10", "Root") + article("11", "Reply", root="10"))
        self.assertEqual(records[1]["id"], "11")
        self.assertEqual(records[1]["root_comment_id"], "10")
        self.assertIsNone(records[1]["parent_comment_id"])
        self.assertTrue(records[1]["is_reply"])

    def test_parent_without_permalink_never_steals_child_id_or_text(self):
        html = '<div role="article" aria-label="Bình luận của A"><div dir="auto">Root</div>'
        records = self.read(html + article("11", "Reply", root="10") + '</div>')
        self.assertIsNone(records[0]["id"])
        self.assertEqual(records[0]["text"], "Root")
        self.assertEqual(records[1]["id"], "11")

    def test_reply_with_own_comment_id_uses_nested_root(self):
        records = self.read(article("10", "Root", article("11", "Reply", label="Reply by")))
        self.assertEqual(records[1]["id"], "11")
        self.assertEqual(records[1]["root_comment_id"], "10")
        self.assertEqual(records[1]["parent_comment_id"], "10")

    def test_fallback_text_excludes_nested_replies_and_action_labels(self):
        html = '<div role="article" aria-label="Comment by A"><span>Own body</span>'
        html += '<button role="button">Reply</button>' + article("2", "Child", root="1") + '</div>'
        records = self.read(html)
        self.assertEqual(records[0]["text"], "Own body")

    def test_multiple_paragraphs_keep_all_text_without_repeating_nested_blocks(self):
        html = '<div role="article" aria-label="Comment by A">'
        html += '<div dir="auto"><div dir="auto">First</div></div><div dir="auto">Second</div></div>'
        self.assertEqual(self.read(html)[0]["text"], "First\nSecond")

    def test_fallback_keeps_links_inside_comment_body(self):
        html = '<div role="article" aria-label="Comment by A"><span>Visit '
        html += '<a href="https://example.org">our website</a></span></div>'
        self.assertEqual(self.read(html)[0]["text"], "Visit our website")

    def test_author_from_aria_label_when_only_avatar_link_exists(self):
        html = '<div role="article" aria-label="Bình luận dưới tên Nguyễn Văn An vào 1 ngày trước">'
        html += '<a href="https://www.facebook.com/profile.php?id=42&comment_id=10"><img alt="Ảnh đại diện"></a>'
        html += '<div dir="auto">Nội dung bình luận</div>'
        html += '<a href="https://www.facebook.com/page/posts/123?comment_id=10">1 ngày</a></div>'
        record = self.read(html)[0]
        self.assertEqual(record["author"], "Nguyễn Văn An")
        self.assertEqual(record["author_url"], "https://www.facebook.com/profile.php?id=42")
        self.assertEqual(record["url"], "https://www.facebook.com/page/posts/123?comment_id=10")
        self.assertEqual(record["posted_raw"], "1 ngày")

    def test_author_label_without_any_profile_anchor(self):
        records = self.read('<div role="article" aria-label="Comment by Alice on Wednesday">'
                            '<span dir="auto">Full comment</span></div>')
        self.assertEqual(records[0]["author"], "Alice")
        self.assertEqual(records[0]["text"], "Full comment")


if __name__ == "__main__":
    unittest.main()
