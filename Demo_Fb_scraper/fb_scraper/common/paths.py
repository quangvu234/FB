"""Đường dẫn gốc dùng chung, không phụ thuộc thư mục terminal đang đứng."""
from pathlib import Path

# paths.py nằm trong fb_scraper/common; đi lên hai cấp để về thư mục project.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
