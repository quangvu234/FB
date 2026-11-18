"""Thiết lập database tạm và agent giả dùng chung cho kiểm thử lưu trữ."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fb_scraper.agent import mode as agent_mode
from fb_scraper.storage import database as storage
from fb_scraper.storage.records import post_view


class PersistenceFixture:
    """Chỉ cung cấp dữ liệu/hàm hỗ trợ; các ca kiểm thử nằm trong test_*.py."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "project" / "data"
        for name, value in {
            "DATA": self.data, "IMG_DIR": self.data / "images",
            "DB_PATH": self.data / "posts.db", "JSONL_PATH": self.data / "posts.jsonl",
        }.items():
            override = patch.object(storage, name, value)
            override.start()
            self.addCleanup(override.stop)
        override = patch.object(agent_mode, "DATA", self.data)
        override.start()
        self.addCleanup(override.stop)

    def persist(self, db, post, source):
        result = agent_mode.persist_agent_post(db, post, source)
        storage.export_jsonl(db)
        return result

    def rows(self):
        return [post_view(json.loads(line)) for line in storage.JSONL_PATH.read_text(encoding="utf-8").splitlines()]

    def post(self, number=1):
        return agent_mode.Post(
            url=f"https://www.facebook.com/example/posts/{number}",
            author="Tác giả", text="Nội dung bài viết dùng để kiểm tra lưu dữ liệu.",
        )

    async def run_fake_agent(self, behavior, max_posts=2, stop_error=None):
        post = self.post().model_dump()

        class FakeAgent:
            def __init__(self, **kwargs):
                self.tools = kwargs["tools"]

            async def run(self, max_steps):
                if behavior != "final_only":
                    await self.tools.registry.execute_action("save_fb_post", post)
                if behavior == "error":
                    raise RuntimeError("LLM disconnected")
                final = json.dumps({"posts": [post]}) if behavior == "final_only" else None
                return SimpleNamespace(final_result=lambda: final)

        with patch.object(agent_mode, "Agent", FakeAgent), \
             patch.object(agent_mode, "create_llm", return_value=object()), \
             patch.object(agent_mode, "_get_browser", return_value=SimpleNamespace(stop=AsyncMock(side_effect=stop_error))), \
             patch.object(agent_mode, "start_agent_browser", new=AsyncMock()):
            return await agent_mode.run_agent("https://www.facebook.com/example", max_posts)
