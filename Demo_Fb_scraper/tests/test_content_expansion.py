"""Mở nội dung dài trên DOM thật, gồm nút thay đổi vị trí và tải bất đồng bộ."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright

from fb_scraper.browser.launcher import find_chrome
from fb_scraper.common.page_actions import expand_see_more
from fb_scraper.common.content import comment_author, fuller_text
from fb_scraper.posts import comments


class ContentTextTests(unittest.TestCase):
    def test_name_from_real_vietnamese_and_english_labels(self):
        for label, expected in [
            ("Bình luận dưới tên Luật Khoa tạp chí vào 1 ngày trước", "Luật Khoa tạp chí"),
            ("Bình luận của Nguyễn Văn An", "Nguyễn Văn An"),
            ("Reply by Alice on Wednesday", "Alice"),
            ("Trả lời dưới tên Người tham gia ẩn danh vào 2 giờ trước", "Người tham gia ẩn danh"),
        ]:
            self.assertEqual(comment_author(label), expected)

    def test_expanded_shorter_text_wins_over_ui_marker(self):
        self.assertEqual(fuller_text("Nội dung… Xem thêm", "Nội dung đầy đủ"), "Nội dung đầy đủ")
        self.assertEqual(fuller_text("Nội dung đầy đủ", "Nội dung… Xem thêm"), "Nội dung đầy đủ")


class ContentExpansionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            executable = find_chrome()
        except RuntimeError as error:
            self.skipTest(str(error))
        self.playwright = await async_playwright().start()
        self.addAsyncCleanup(self.playwright.stop)
        self.browser = await self.playwright.chromium.launch(executable_path=str(executable), headless=True)
        self.addAsyncCleanup(self.browser.close)
        self.page = await self.browser.new_page()

    async def test_expands_more_than_fifteen_without_skipping_removed_buttons(self):
        pieces = ['<nav><button onclick="window.outsideClicked=true">Xem thêm</button></nav><main role="main">']
        for index in range(24):
            tag = ("button", "span", "a", "div")[index % 4]
            role = 'role="button"' if tag in {"span", "div"} else ''
            pieces.append(f'<section id="body-{index}">Short… <{tag} {role} onclick="this.parentElement.textContent=\'Complete {index}\'">Xem thêm</{tag}></section>')
        await self.page.set_content(''.join(pieces) + '</main>')
        self.assertEqual(await expand_see_more(self.page), 24)
        for index in range(24):
            self.assertEqual(await self.page.locator(f'#body-{index}').inner_text(), f'Complete {index}')
        self.assertIsNone(await self.page.evaluate('window.outsideClicked'))

    async def test_waits_for_async_content_update(self):
        await self.page.set_content('<main role="main"><p id="body">Short… '
            '<span role="button" onclick="setTimeout(()=>this.parentElement.textContent=\'Complete after load\',250)">See more</span></p></main>')
        await expand_see_more(self.page)
        self.assertEqual(await self.page.locator('#body').inner_text(), 'Complete after load')

    async def test_newly_loaded_reply_is_expanded_before_saving(self):
        await self.page.set_content('<main role="main"><div role="article" aria-label="Bình luận dưới tên A vào 1 giờ trước">'
            '<div data-comment-text dir="auto">Root</div><a href="https://www.facebook.com/page/posts/1?comment_id=10">1 giờ</a></div></main>')

        async def reveal(_page):
            await self.page.locator('main').evaluate('''el => el.insertAdjacentHTML('beforeend',
              `<div role="article" aria-label="Trả lời dưới tên B vào 1 giờ trước">
                <div data-comment-text dir="auto">Short… <span role="button"
                  onclick="this.parentElement.textContent='Full reply content'">Xem thêm</span></div>
                <a href="https://www.facebook.com/page/posts/1?comment_id=10&reply_comment_id=11">1 giờ</a></div>`)''')
            return True

        with patch.object(self.page, 'goto', new=AsyncMock()), \
             patch.object(comments, 'human_pause', new=AsyncMock()), \
             patch.object(comments, 'expand_replies', new=reveal):
            result = await comments.scrape_top_comments(SimpleNamespace(new_page=AsyncMock(return_value=self.page)),
                                                        'https://www.facebook.com/page/posts/1', 2)
        self.assertEqual(result[1]['author'], 'B')
        self.assertEqual(result[1]['text'], 'Full reply content')


if __name__ == '__main__':
    unittest.main()
