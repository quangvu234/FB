"""Kiểm tra endpoint, hồ sơ thực tế và vòng đời Chrome bằng browser giả."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fb_scraper.agent import mode as agent_mode
from fb_scraper.browser import connection as connection
from fb_scraper.browser import settings as settings
from fb_scraper.browser import launcher as launcher


class BrowserConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.enterContext(patch.dict(os.environ, {
            "USE_SYSTEM_CHROME": "1", "CHROME_USER_DATA_DIR": str(self.data),
            "CHROME_PROFILE_DIRECTORY": "Profile 2", "BROWSER_CDP_URL": "", "USE_LOCAL_BROWSER": "0",
        }))
        self.enterContext(patch.object(settings.socket, "create_connection"))

    def endpoint(self):
        (self.data / "DevToolsActivePort").write_text("54321\r\n/devtools/browser/example\r\n", encoding="utf-8")

    def test_reads_native_websocket_without_http_discovery(self):
        self.endpoint()
        self.assertEqual(settings.get_cdp_url(), "ws://127.0.0.1:54321/devtools/browser/example")

    def test_missing_endpoint_explains_manual_setup(self):
        with self.assertRaisesRegex(RuntimeError, "Profile 2.*chrome://inspect/#remote-debugging"):
            settings.get_cdp_url()

    def test_rejects_malformed_endpoint_instead_of_opening_blank_profile(self):
        for content in ("", "9222", "abc\n/devtools/browser/x", "0\n/devtools/browser/x",
                        "65536\n/devtools/browser/x", "9222\nhttps://example.com/"):
            with self.subTest(content=content):
                (self.data / "DevToolsActivePort").write_text(content, encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    settings.get_cdp_url()

    def test_stale_endpoint_is_rejected_before_connecting(self):
        self.endpoint()
        with patch.object(settings.socket, "create_connection", side_effect=ConnectionRefusedError):
            with self.assertRaisesRegex(RuntimeError, "không còn hoạt động"):
                settings.get_cdp_url()

    def test_legacy_mode_keeps_custom_cdp_url(self):
        with patch.dict(os.environ, {"USE_SYSTEM_CHROME": "0", "BROWSER_CDP_URL": "http://localhost:9333"}):
            self.assertEqual(settings.get_cdp_url(), "http://localhost:9333")
        with patch.dict(os.environ, {"USE_SYSTEM_CHROME": "0"}):
            self.assertEqual(settings.get_cdp_url("http://localhost:9444"), "http://localhost:9444")

    def test_system_mode_overrides_local_browser_and_keeps_chrome_open(self):
        self.endpoint()
        with patch.dict(os.environ, {"USE_LOCAL_BROWSER": "1"}), patch.object(agent_mode, "Browser") as browser:
            self.assertIs(agent_mode._get_browser(), browser.return_value)
        browser.assert_called_once_with(cdp_url="ws://127.0.0.1:54321/devtools/browser/example", keep_alive=True)

    def test_missing_system_endpoint_does_not_create_a_new_browser(self):
        with patch.object(agent_mode, "Browser") as browser:
            with self.assertRaises(RuntimeError):
                agent_mode._get_browser()
        browser.assert_not_called()

    def test_local_mode_does_not_require_a_system_endpoint(self):
        with patch.dict(os.environ, {"USE_SYSTEM_CHROME": "0", "USE_LOCAL_BROWSER": "1"}), \
             patch.object(launcher.subprocess, "Popen") as launch, patch.object(agent_mode, "Browser") as browser:
            agent_mode._get_browser()
        launch.assert_not_called()
        browser.assert_called_once_with(cdp_url=settings.LOCAL_CDP_URL, keep_alive=True)

    def test_legacy_agent_cdp_mode_also_keeps_browser_open(self):
        with patch.dict(os.environ, {"USE_SYSTEM_CHROME": "0", "USE_LOCAL_BROWSER": "0"}), \
             patch.object(agent_mode, "Browser") as browser:
            agent_mode._get_browser()
        browser.assert_called_once_with(cdp_url=settings.DEFAULT_CDP_URL, keep_alive=True)

    async def test_profile_check_uses_actual_path_and_rejects_another_profile(self):
        for name, matches in (("Profile 2", True), ("Default", False)):
            with self.subTest(profile=name):
                page = SimpleNamespace(evaluate=AsyncMock(return_value=str(self.data / name)))
                if matches:
                    await connection.verify_profile(page)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Hồ sơ thực tế"):
                        await connection.verify_profile(page)

    async def context_fixture(self, profile):
        self.endpoint()
        probe = SimpleNamespace(
            goto=AsyncMock(), evaluate=AsyncMock(return_value=str(self.data / profile)), close=AsyncMock(),
        )
        ctx = SimpleNamespace(new_page=AsyncMock(return_value=probe), close=AsyncMock())
        browser = SimpleNamespace(contexts=[ctx], close=AsyncMock())
        pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)))
        manager = AsyncMock()
        manager.__aenter__.return_value = pw
        return manager, ctx, browser, probe

    async def test_context_keeps_user_browser_open_and_closes_only_its_probe(self):
        manager, ctx, browser, probe = await self.context_fixture("Profile 2")
        with patch.object(connection, "async_playwright", return_value=manager):
            async with connection.browser_context() as result:
                self.assertIs(result, ctx)
        probe.close.assert_awaited_once()
        browser.close.assert_not_awaited()
        ctx.close.assert_not_awaited()

    async def test_wrong_profile_stops_before_caller_can_collect(self):
        manager, ctx, browser, probe = await self.context_fixture("Default")
        with patch.object(connection, "async_playwright", return_value=manager):
            with self.assertRaisesRegex(RuntimeError, "hồ sơ yêu cầu"):
                async with connection.browser_context():
                    self.fail("Caller must not receive the wrong profile")
        probe.close.assert_awaited_once()
        browser.close.assert_not_awaited()

    async def test_agent_checks_profile_and_closes_probe_on_failure(self):
        probe = SimpleNamespace(evaluate=AsyncMock(return_value=str(self.data / "Default")))
        browser = SimpleNamespace(start=AsyncMock(), new_page=AsyncMock(return_value=probe), close_page=AsyncMock())
        with self.assertRaisesRegex(RuntimeError, "hồ sơ yêu cầu"):
            await connection.start_agent_browser(browser)
        browser.close_page.assert_awaited_once_with(probe)

    def test_launcher_passes_configured_user_data_and_profile(self):
        program_files = self.data / "program files"
        executable = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
        executable.parent.mkdir(parents=True)
        executable.touch()
        (self.data / "Profile 5").mkdir()
        with patch.dict(os.environ, {"ProgramFiles": str(program_files), "CHROME_PROFILE_DIRECTORY": "Profile 5"}), \
             patch.object(launcher.subprocess, "Popen") as launch:
            launcher.open_chrome()
        self.assertIn(f"--user-data-dir={self.data}", launch.call_args.args[0])
        self.assertIn("--profile-directory=Profile 5", launch.call_args.args[0])

    def test_profile_cannot_escape_user_data_directory(self):
        with patch.dict(os.environ, {"CHROME_PROFILE_DIRECTORY": "../other"}):
            with self.assertRaises(ValueError):
                settings.profile_directory()


class DedicatedProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "persistent-profile"
        self.enterContext(patch.dict(os.environ, {
            "USE_SYSTEM_CHROME": "0", "USE_LOCAL_BROWSER": "1",
            "CHROME_USER_DATA_DIR": str(self.data), "CHROME_PROFILE_DIRECTORY": "Default",
            "BROWSER_CDP_URL": "http://127.0.0.1:9223",
        }))
        self.enterContext(patch.object(launcher, "find_chrome", return_value=Path("chrome.exe")))

    def test_new_browser_opens_with_fixed_profile_and_loopback_cdp(self):
        with patch.object(launcher, "_debugging_ready", side_effect=[False, True]), \
             patch.object(launcher, "_port_open", return_value=False), \
             patch.object(launcher.subprocess, "Popen") as launch:
            endpoint = launcher.ensure_local_chrome()
        args = launch.call_args.args[0]
        self.assertEqual(endpoint, "http://127.0.0.1:9223")
        self.assertIn(f"--user-data-dir={self.data}", args)
        self.assertIn("--profile-directory=Default", args)
        self.assertIn("--remote-debugging-port=9223", args)
        self.assertIn("--remote-debugging-address=127.0.0.1", args)
        self.assertIn("--no-first-run", args)
        self.assertEqual(args[-1], "https://www.facebook.com/")

    def test_existing_browser_is_reused_without_relaunch(self):
        with patch.object(launcher, "_debugging_ready", return_value=True), \
             patch.object(launcher.subprocess, "Popen") as launch:
            self.assertEqual(launcher.ensure_local_chrome(), "http://127.0.0.1:9223")
        launch.assert_not_called()

    def test_launch_does_not_remove_existing_profile_data(self):
        self.data.mkdir()
        marker = self.data / "existing-session-marker"
        marker.write_text("keep", encoding="utf-8")
        with patch.object(launcher, "_debugging_ready", side_effect=[False, True]), \
             patch.object(launcher, "_port_open", return_value=False), patch.object(launcher.subprocess, "Popen"):
            launcher.ensure_local_chrome()
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_occupied_port_does_not_launch_another_browser(self):
        with patch.object(launcher, "_debugging_ready", return_value=False), \
             patch.object(launcher, "_port_open", return_value=True), \
             patch.object(launcher.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "Cổng CDP"):
                launcher.ensure_local_chrome()
        launch.assert_not_called()

    def test_startup_timeout_is_reported_without_switching_profiles(self):
        with patch.object(launcher, "_debugging_ready", return_value=False), \
             patch.object(launcher, "_port_open", return_value=False), \
             patch.object(launcher.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "Chrome chưa mở được"):
                launcher.ensure_local_chrome(timeout=0)
        launch.assert_called_once()

    def test_local_mode_rejects_remote_or_invalid_debugging_urls(self):
        for endpoint in ("http://example.com:9223", "http://0.0.0.0:9223", "https://127.0.0.1:9223",
                         "http://127.0.0.1:0", "http://127.0.0.1:9223/path", "http://127.0.0.1:9223?x=1"):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"BROWSER_CDP_URL": endpoint}):
                with self.assertRaises(ValueError):
                    settings.local_cdp_url()

    def test_automation_cannot_launch_against_personal_user_data(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root),
                                    "CHROME_USER_DATA_DIR": str(self.root / "Google" / "Chrome" / "User Data")}):
            with self.assertRaisesRegex(ValueError, "thư mục riêng"):
                launcher.local_launch_arguments()

    async def test_collectors_start_chrome_then_check_the_dedicated_profile(self):
        probe = SimpleNamespace(goto=AsyncMock(), evaluate=AsyncMock(return_value=str(self.data / "Default")), close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=probe), close=AsyncMock())
        browser = SimpleNamespace(contexts=[context], close=AsyncMock())
        pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)))
        manager = AsyncMock()
        manager.__aenter__.return_value = pw
        with patch.object(connection, "ensure_local_chrome", return_value=settings.LOCAL_CDP_URL) as start, \
             patch.object(connection, "async_playwright", return_value=manager):
            async with connection.browser_context() as result:
                self.assertIs(result, context)
        start.assert_called_once()
        pw.chromium.connect_over_cdp.assert_awaited_once_with(settings.LOCAL_CDP_URL, timeout=120000)
        probe.close.assert_awaited_once()
        context.close.assert_not_awaited()
        browser.close.assert_not_awaited()

    async def test_agent_uses_the_same_startup_and_profile_validation(self):
        probe = SimpleNamespace(evaluate=AsyncMock(return_value=str(self.data / "Default")))
        browser = SimpleNamespace(start=AsyncMock(), new_page=AsyncMock(return_value=probe), close_page=AsyncMock())
        with patch.object(connection, "ensure_local_chrome", return_value=settings.LOCAL_CDP_URL) as start:
            await connection.start_agent_browser(browser)
        start.assert_called_once()
        browser.start.assert_awaited_once()
        browser.close_page.assert_awaited_once_with(probe)


if __name__ == "__main__":
    unittest.main()
