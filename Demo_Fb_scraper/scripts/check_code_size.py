"""Kiểm tra các file Python của project đều dưới 300 dòng."""
import sys
from pathlib import Path

MAX_LINES = 299


def main():
    project_folder = Path(__file__).resolve().parent.parent
    python_files = [project_folder / "main.py"]

    # Chỉ quét mã nguồn do project quản lý, không quét thư viện và hồ sơ Chrome.
    for folder_name in ("fb_scraper", "tests", "scripts"):
        folder = project_folder / folder_name
        for path in folder.rglob("*.py"):
            python_files.append(path)

    oversized_files = []
    for path in sorted(python_files):
        source = path.read_text(encoding="utf-8-sig")
        line_count = len(source.splitlines())
        relative_path = path.relative_to(project_folder)
        print(f"{line_count:3} dòng  {relative_path}")

        if line_count > MAX_LINES:
            oversized_files.append(relative_path)

    if oversized_files:
        print("\nCác file vượt giới hạn:")
        for path in oversized_files:
            print("  " + str(path))
        return 1

    print(f"\nĐạt: {len(python_files)} file đều dưới 300 dòng.")
    print("Đã tính cả dòng trống và chú thích.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
