"""Vòng đời tiến trình và hủy collector vẫn lưu được dữ liệu."""
import asyncio
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fb_scraper.web.jobs import JobManager
from fb_scraper.web import worker
from fb_scraper.storage import database as storage
from tests.persistence_fixtures import PersistenceFixture

FAKE_WORKER = '''import json, sys
config = json.loads(sys.stdin.readline())
print('@@SCRAPER_EVENT ' + json.dumps({'type':'source','completed':0,'total':1,'label':'Test'}), flush=True)
print('Saved fixture', flush=True)
if config.get('slow'):
    sys.stdin.readline()
    raise SystemExit(130)
print('@@SCRAPER_EVENT ' + json.dumps({'type':'source_done','completed':1,'total':1}), flush=True)
'''


class WebJobTests(unittest.TestCase):
    def setUp(self):
        self.manager = JobManager()
        self.addCleanup(self.manager.close)
        original = subprocess.Popen

        def launch(_args, **kwargs):
            return original([sys.executable, "-u", "-c", FAKE_WORKER], **kwargs)

        self.enterContext(patch("fb_scraper.web.jobs.subprocess.Popen", side_effect=launch))

    def finished(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.manager.snapshot()["current"]
            if current["status"] not in {"running", "stopping"}:
                return current
            time.sleep(0.01)
        self.fail("Worker did not finish")

    def test_completed_worker_reports_progress_and_logs(self):
        self.manager.start({"plan": [{"kind": "keyword", "value": "test"}]})
        current = self.finished()
        self.assertEqual(current["status"], "completed")
        self.assertEqual(current["completed"], 1)
        self.assertEqual(current["logs"], ["Saved fixture"])

    def test_only_one_worker_and_stop_is_graceful(self):
        self.manager.start({"plan": [{}], "slow": True})
        with self.assertRaises(RuntimeError):
            self.manager.start({"plan": []})
        self.assertTrue(self.manager.stop())
        current = self.finished()
        self.assertEqual(current["status"], "cancelled")
        self.assertEqual(current["exit_code"], 130)


class WebWorkerTests(PersistenceFixture, unittest.IsolatedAsyncioTestCase):
    async def test_cancel_exports_committed_posts_and_closes_own_page(self):
        from fb_scraper.browser import connection
        from fb_scraper.posts import pipeline
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        manager = AsyncMock()
        manager.__aenter__.return_value = context

        async def collect(_page, _context, db, *_args):
            storage.save_post(db, {"post_id": "1", "text": "Committed before cancellation"})
            raise asyncio.CancelledError()

        with patch.object(connection, "browser_context", return_value=manager), \
             patch.object(pipeline, "collect_source_posts", new=collect), \
             patch.object(worker, "watch_stop", return_value=None):
            result = await worker.collect({"plan": [{"kind": "keyword", "value": "test"}],
                                           "options": {"max_posts": 1, "max_comments": 0}})
        self.assertEqual(result, 130)
        self.assertEqual(self.rows()[0]["post_id"], "1")
        page.close.assert_awaited_once()
        manager.__aexit__.assert_awaited_once()

    async def test_url_sources_route_to_existing_entity_collector_in_same_context(self):
        from fb_scraper.browser import connection
        from fb_scraper.entities import collector
        context = object()
        manager = AsyncMock()
        manager.__aenter__.return_value = context
        plan = [{"kind": "profile", "value": "https://www.facebook.com/example"},
                {"kind": "group", "value": "https://www.facebook.com/groups/123"}]
        with patch.object(connection, "browser_context", return_value=manager), \
             patch.object(collector, "collect_entities", new=AsyncMock()) as collect, \
             patch.object(worker, "watch_stop", return_value=None):
            result = await worker.collect({"plan": plan, "options": {"max_posts": 2}})
        self.assertEqual(result, 0)
        self.assertEqual(collect.await_count, 2)
        self.assertIs(collect.await_args_list[0].args[0], context)
        self.assertEqual(collect.await_args_list[1].args[2], "group")


if __name__ == "__main__":
    unittest.main()
