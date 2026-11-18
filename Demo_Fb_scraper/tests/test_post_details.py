"""Chỉ dùng nội dung đầy đủ của đúng bài, không lấy nhầm bài gợi ý trong permalink."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fb_scraper.posts import details


class PostDetailsTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_content_matches_post_id_and_closes_its_tab(self):
        def article(identity, text):
            return {"text": text, "author": "Tác giả", "imgs": [], "links": [
                {"href": f"https://www.facebook.com/page/posts/{identity}", "text": "1 giờ"}]}

        full_text = "Nội dung bài viết đầy đủ sau khi mở permalink."
        tab = SimpleNamespace(url="https://www.facebook.com/page/posts/1", goto=AsyncMock(), close=AsyncMock(),
                              evaluate=AsyncMock(return_value=[article(2, "Nội dung bài được gợi ý khác."), article(1, full_text)]))
        page = SimpleNamespace(context=SimpleNamespace(new_page=AsyncMock(return_value=tab)))
        post = {"post_id": "1", "url": tab.url, "source": "kw:test", "author": "", "text": "Short… See more"}
        with patch.object(details, "human_pause", new=AsyncMock()), \
             patch.object(details, "expand_see_more", new=AsyncMock()):
            result = await details.complete_post(page, post)
        self.assertEqual(result["text"], full_text)
        self.assertEqual(result["author"], "Tác giả")
        tab.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
