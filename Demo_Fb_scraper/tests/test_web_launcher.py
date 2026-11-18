"""Chạy launcher thật trên Windows từ thư mục khác để kiểm tra CMD và đường dẫn."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Launcher CMD dành cho Windows.")
class WebLauncherTests(unittest.TestCase):
    def test_launcher_help_from_another_working_directory(self):
        launcher = Path(__file__).resolve().parents[1] / "start_ui.cmd"
        quoted_path = str(launcher).replace("'", "''")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"& '{quoted_path}' --help"],
                cwd=directory, stdin=subprocess.DEVNULL, capture_output=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--port", result.stdout)
        self.assertNotIn("is not recognized", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
