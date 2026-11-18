"""Khởi động giao diện trong cùng Chrome Facebook, giữ phiên và dùng lại tab."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fb_scraper.browser import workspace
from fb_scraper.web import server


class WorkspaceBrowserTests(unittest.IsolatedAsyncioTestCase):
    def manager(self, pages=(), new_pages=()):
        context = SimpleNamespace(pages=list(pages), new_page=AsyncMock(side_effect=list(new_pages)))
        manager = AsyncMock()
        manager.__aenter__.return_value = context
        return manager, context

    async def test_opens_facebook_and_ui_and_keeps_both_tabs(self):
        facebook = SimpleNamespace(url="about:blank", goto=AsyncMock(), close=AsyncMock())
        ui = SimpleNamespace(url="about:blank", goto=AsyncMock(), bring_to_front=AsyncMock(), close=AsyncMock())
        manager, context = self.manager(new_pages=[facebook, ui])
        with patch.object(workspace, "browser_context", return_value=manager):
            await workspace.open_workspace("http://127.0.0.1:8765")
        self.assertEqual(context.new_page.await_count, 2)
        self.assertEqual(facebook.goto.await_args.args[0], "https://www.facebook.com/")
        self.assertEqual(ui.goto.await_args.args[0], "http://127.0.0.1:8765")
        ui.bring_to_front.assert_awaited_once()
        facebook.close.assert_not_awaited()
        ui.close.assert_not_awaited()
        manager.__aexit__.assert_awaited_once()

    async def test_reuses_existing_facebook_and_ui_without_reloading_inputs(self):
        facebook = SimpleNamespace(url="https://www.facebook.com/groups/123", goto=AsyncMock())
        ui = SimpleNamespace(url="http://127.0.0.1:8765/#results", goto=AsyncMock(), bring_to_front=AsyncMock())
        manager, context = self.manager(pages=[facebook, ui])
        with patch.object(workspace, "browser_context", return_value=manager):
            await workspace.open_workspace("http://127.0.0.1:8765")
        context.new_page.assert_not_awaited()
        ui.goto.assert_not_awaited()
        facebook.goto.assert_not_awaited()
        ui.bring_to_front.assert_awaited_once()

    async def test_facebook_load_error_still_opens_ui(self):
        facebook = SimpleNamespace(url="about:blank", goto=AsyncMock(side_effect=TimeoutError()))
        ui = SimpleNamespace(url="about:blank", goto=AsyncMock(), bring_to_front=AsyncMock())
        manager, _context = self.manager(new_pages=[facebook, ui])
        with patch.object(workspace, "browser_context", return_value=manager):
            await workspace.open_workspace("http://127.0.0.1:8766")
        ui.goto.assert_awaited_once()


class WorkspaceStartupTests(unittest.TestCase):
    def test_server_serves_while_tabs_open_in_background(self):
        instance = Mock(server_port=8765)
        thread = Mock()

        def serve():
            thread.start.assert_called_once()
            raise KeyboardInterrupt()

        instance.serve_forever.side_effect = serve
        with patch.object(server, "AppServer", return_value=instance), \
             patch.object(server.threading, "Thread", return_value=thread) as launch, \
             patch("fb_scraper.storage.database.init_db", return_value=Mock()):
            server.run_cli(["--open"])
        launch.assert_called_once_with(target=server.open_startup_tabs, args=("http://127.0.0.1:8765",), daemon=True)
        instance.manager.close.assert_called_once()
        instance.server_close.assert_called_once()

    def test_without_open_does_not_launch_chrome(self):
        instance = Mock(server_port=8765)
        instance.serve_forever.side_effect = KeyboardInterrupt()
        with patch.object(server, "AppServer", return_value=instance), \
             patch.object(server.threading, "Thread") as launch, \
             patch("fb_scraper.storage.database.init_db", return_value=Mock()):
            server.run_cli([])
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
