"""Điểm chạy chung: python main.py <lệnh> [tùy chọn]."""
import argparse
import sys


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Thu thập dữ liệu Facebook.")
    parser.add_argument(
        "command",
        choices=("posts", "entity", "search", "agent", "browser", "storage"),
        help="posts: bài viết; entity: cá nhân/nhóm; search: tìm kiếm; "
             "agent: LLM; browser: mở Chrome; storage: xuất dữ liệu",
    )
    # REMAINDER giữ nguyên các tùy chọn phía sau lệnh để CLI tương ứng đọc.
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="tùy chọn của lệnh")
    args = parser.parse_args()

    if args.command == "posts":
        from fb_scraper.posts.collector import run_cli
    elif args.command == "entity":
        from fb_scraper.entities.collector import run_cli
    elif args.command == "search":
        from fb_scraper.search.collector import run_cli
    elif args.command == "agent":
        from fb_scraper.agent.mode import run_cli
    elif args.command == "browser":
        from fb_scraper.browser.connection import run_cli
    else:
        from fb_scraper.storage.database import run_cli

    run_cli(args.arguments)


if __name__ == "__main__":
    main()
