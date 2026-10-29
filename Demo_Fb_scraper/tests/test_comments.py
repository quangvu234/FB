"""Các tình huống đọc bình luận dựa trên nhãn thực tế của Facebook."""
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fb_scraper.posts import comments as collector
class CommentTests(unittest.IsolatedAsyncioTestCase):
    def comment(self, identity, text=None):
        return {"id": str(identity), "label": f"Bình luận dưới tên Người {identity} vào 18 giờ trước", "text": text or f"Người {identity}\nNội dung bình luận {identity}\nTrả lời"}

    def test_actual_vietnamese_label_and_english_labels_are_accepted(self):
        collected = {}
        records = [self.comment(1)]
        for index, label in enumerate(("Bình luận của Người A", "Comment by User B", "Reply by User C"), 2):
            records.append({"id": str(index), "label": label, "text": f"Comment {index}"})
        records.append({"id": "post", "label": "Bài viết của Page", "text": "Nội dung bài viết"})
        collector.merge_comments(collected, records)
        self.assertEqual(len(collected), 4)
        self.assertNotIn("post", collected)

    def test_same_comment_id_updates_expanded_text_without_duplicate(self):
        collected = {}
        collector.merge_comments(collected, [self.comment(1, "Nội dung… Xem thêm")])
        collector.merge_comments(collected, [self.comment(1, "Nội dung đầy đủ"), self.comment(2)])
        self.assertEqual(len(collected), 2)
        self.assertEqual(collected["1"], "Nội dung đầy đủ")

    async def scrape_fixture(self, snapshots, requested):
        page = SimpleNamespace(
            url="https://www.facebook.com/page/posts/123", goto=AsyncMock(), close=AsyncMock(),
            evaluate=AsyncMock(side_effect=snapshots),
        )
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        load_more = AsyncMock(return_value=True)
        with patch.object(collector, "human_pause", new=AsyncMock()), \
             patch.object(collector, "expand_see_more", new=AsyncMock()), \
             patch.object(collector, "load_more_comments", new=load_more):
            result = await collector.scrape_top_comments(context, page.url, requested)
        page.close.assert_awaited_once()
        return result, load_more

    async def test_loads_more_and_deduplicates_batches_to_requested_limit(self):
        first = [self.comment(index) for index in range(1, 7)]
        second = [self.comment(index) for index in range(1, 22)]
        result, load_more = await self.scrape_fixture([first, second], 20)
        self.assertEqual(len(result), 20)
        self.assertEqual(len(set(result)), 20)
        self.assertEqual(result[0], first[0]["text"])
        load_more.assert_awaited_once()

    async def test_partial_comments_survive_later_browser_error(self):
        result, _ = await self.scrape_fixture([[self.comment(1)], RuntimeError("navigation failed")], 20)
        self.assertEqual(result, [self.comment(1)["text"]])

    async def test_large_request_is_not_cut_off_after_40_batches(self):
        snapshots = [[self.comment(index) for index in range(1, batch * 10 + 1)] for batch in range(1, 46)]
        with redirect_stdout(io.StringIO()):
            result, load_more = await self.scrape_fixture(snapshots, 450)
        self.assertEqual(len(result), 450)
        self.assertEqual(load_more.await_count, 44)

    async def test_stops_when_no_additional_comments_load(self):
        first = [self.comment(1)]
        result, load_more = await self.scrape_fixture([first] * 4, 20)
        self.assertEqual(len(result), 1)
        self.assertEqual(load_more.await_count, 3)

    def test_load_more_filter_does_not_match_send_or_reply_buttons(self):
        for name in ("Xem thêm bình luận", "View more comments", "Xem các bình luận trước"):
            self.assertRegex(name, collector.COMMENT_MORE_RE)
        for name in ("Đăng bình luận", "Trả lời", "Ẩn hoặc báo cáo bình luận này", "Xem 4 câu trả lời"):
            self.assertNotRegex(name, collector.COMMENT_MORE_RE)


if __name__ == "__main__":
    unittest.main()
