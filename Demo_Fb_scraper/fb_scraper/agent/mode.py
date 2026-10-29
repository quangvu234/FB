"""
Chế độ Browser Use: LLM điều khiển Chrome qua CDP theo cấu hình trong .env.
Dùng khi selector của fb_scraper/posts/collector.py bị hỏng do Facebook đổi giao diện.

  Cấu hình nhà cung cấp và API key trong .env.
  python main.py agent https://www.facebook.com/Vietcombank --max-posts 5
"""
import argparse
import asyncio
import os
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

from fb_scraper.browser.connection import create_agent_browser, start_agent_browser
from browser_use import ActionResult, Agent, Browser, ChatAnthropic, ChatGroq, ChatOpenAI, Tools
from fb_scraper.common.urls import canonical_post_url, make_post_id
from fb_scraper.common.models import Post as FBPost, PostBatch as FBPosts
# "as" đặt tên khác cho cùng một class; schema gốc ở fb_scraper/common/models.py.
from fb_scraper.storage.database import DATA, export_agent_output, export_jsonl, init_db, print_storage_paths, save_post


def _get_browser():
    return create_agent_browser(Browser)


def _is_placeholder_key(value: str | None) -> bool:
    if not value:
        return True
    normalized_value = value.strip().lower()
    placeholders = {
        "your_openai_key_here",
        "your_anthropic_key_here",
        "your_groq_key_here",
        "changeme",
        "example",
        "demo",
        "test",
        "fake",
        "placeholder",
    }
    if normalized_value in placeholders:
        return True
    if normalized_value.startswith("your_") and normalized_value.endswith("_here"):
        return True
    return False


def create_llm():
    provider_setting = os.getenv("LLM_PROVIDER")
    if not provider_setting:
        provider_setting = "anthropic"
    provider = provider_setting.lower()

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if _is_placeholder_key(api_key):
            raise RuntimeError(
                "OPENAI_API_KEY đang là placeholder hoặc chưa được điền. Vui lòng thay bằng key thật từ https://platform.openai.com/api-keys"
            )
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=api_key,
        )

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if _is_placeholder_key(api_key):
            raise RuntimeError(
                "GROQ_API_KEY đang là placeholder hoặc chưa được điền. Vui lòng thay bằng key thật từ https://console.groq.com/keys"
            )
        return ChatGroq(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            api_key=api_key,
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if _is_placeholder_key(api_key):
        raise RuntimeError(
            "ANTHROPIC_API_KEY đang là placeholder hoặc chưa được điền. Vui lòng thay bằng key thật từ https://console.anthropic.com/"
        )
    return ChatAnthropic(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        api_key=api_key,
    )


def persist_agent_post(db, post: FBPost, source: str) -> FBPost:
    if not (post.text.strip() or post.images):
        raise ValueError("Bài viết chưa có nội dung hoặc ảnh để lưu.")
    # Dùng cùng cách tạo ID với collector để tránh lưu trùng giữa hai chế độ.
    url = canonical_post_url(post.url)
    updated_fields = {
        "url": url,
        "post_id": make_post_id(url, post.text),
        "source": source,
    }
    # Tạo bản sao đã chuẩn hóa, không sửa trực tiếp object do bên gọi truyền vào.
    post = post.model_copy(update=updated_fields)
    # Agent chỉ đọc nội dung/URL. Các trường ảnh đã tải và OCR thuộc DOM collector.
    local_only_fields = {"image_files", "ocr", "entity_type", "entity_id", "collected_at"}
    post_record = post.model_dump(
        exclude_unset=True,
        exclude=local_only_fields,
    )
    save_post(db, post_record)
    return post


async def run_agent(target_url: str, max_posts: int, max_steps: int = 40) -> FBPosts:
    """Khởi động Chrome, cho LLM đọc bài, lưu từng bài và xuất kết quả khi kết thúc."""
    if max_posts <= 0 or max_steps <= 0:
        raise ValueError("--max-posts và --max-steps phải lớn hơn 0.")
    db = init_db()
    collected: dict[str, FBPost] = {}
    browser = None
    try:
        print_storage_paths()
        llm = create_llm()
        browser = _get_browser()
        await start_agent_browser(browser)
        tools = Tools()

        # Hàm lồng này dùng db và collected của chính lượt chạy hiện tại.
        def store(post: FBPost):
            normalized_url = canonical_post_url(post.url)
            identity = make_post_id(normalized_url, post.text)
            if identity not in collected and len(collected) >= max_posts:
                return False
            saved = persist_agent_post(db, post, target_url)
            collected[saved.post_id] = saved
            print(f"  Đã lưu {saved.post_id} vào SQLite ({len(collected)}/{max_posts})", flush=True)
            return True

        # Đăng ký hành động để LLM có thể gọi hàm lưu bài này.
        @tools.action("Lưu ngay một bài Facebook đã đọc vào SQLite data/posts.db", param_model=FBPost)
        async def save_fb_post(params: FBPost):
            was_saved = store(params)
            if not was_saved:
                return ActionResult(extracted_content="Đã đủ số bài yêu cầu. Hãy kết thúc bằng done.")
            return ActionResult(extracted_content=f"Đã lưu bài. Tổng đã lưu: {len(collected)}/{max_posts}.")

        task = f"""
Mở {target_url}. Chỉ đọc bài đăng công khai, KHÔNG like/comment/share/gửi tin nhắn.
Cuộn xuống và thu thập tối đa {max_posts} bài đăng. Với mỗi bài lấy: url bài viết (permalink),
post_id, tên page/người đăng, nội dung đầy đủ (bấm 'Xem thêm' nếu có), thời gian đăng,
số like/cảm xúc, số bình luận, số chia sẻ, URL ảnh đính kèm, link ngoài và tối đa 3 bình luận nổi bật.
Ngay sau khi đọc MỖI bài, gọi save_fb_post để lưu bài trước khi cuộn tiếp.
Trang /search/posts?q=... là nguồn tìm kiếm, không phải permalink của bài.
Giữ nguyên URL tìm kiếm gồm ?q=... khi điều hướng. Chỉ mở tab phụ để đọc một bài
khi đã thấy permalink cụ thể; nếu không thấy thì để url rỗng và lưu nội dung tại trang hiện tại.
Sau khi đã lưu {max_posts} bài, kết thúc ngay bằng done với danh sách posts đã thu thập.
Nếu gặp captcha/checkpoint thì dừng và báo lại. Không bịa dữ liệu: số đếm/thời gian/ID
không thấy thì để null, url/author/text không thấy thì dùng chuỗi rỗng, danh sách không thấy thì dùng [].
"""
        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            tools=tools,
            output_model_schema=FBPosts,
        )
        history = await agent.run(max_steps=max_steps)
        result = history.final_result()
        if result:
            try:
                final_posts = FBPosts.model_validate_json(result)
            except ValueError:
                if not collected:
                    raise RuntimeError("Agent không trả về JSON bài viết hợp lệ; chưa có bài nào được lưu.")
                print("Agent kết thúc không đúng JSON; dùng các bài đã lưu trong lúc chạy.")
            else:
                for post in final_posts.posts:
                    store(post)
        if not collected:
            raise RuntimeError(
                "Agent chưa thu thập được bài nào. Kiểm tra đăng nhập/URL và log của agent. "
                "Có thể tăng --max-steps nếu chưa hoàn thành."
            )
        return FBPosts(posts=list(collected.values()))
    finally:
        try:
            if collected:
                exported = export_agent_output(list(collected.values()))
                export_status = "chờ cập nhật"
                if exported:
                    export_status = "đã xuất"
                print(
                    f"Đã giữ {len(collected)} bài trong SQLite; JSON agent {export_status}.",
                    flush=True,
                )
            export_jsonl(db)
        finally:
            db.close()
            if browser is not None:
                try:
                    await browser.stop()
                except Exception as exc:
                    print(f"Chưa ngắt được kết nối agent ({type(exc).__name__}); SQLite đã được đóng.", flush=True)


def run_cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--max-posts", type=int, default=5)
    parser.add_argument("--max-steps", type=int, default=40, help="số bước điều khiển trình duyệt tối đa")
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(run_agent(args.url, args.max_posts, args.max_steps))
        print(f"Hoàn tất: {len(result.posts)} bài -> {DATA}")
    except Exception as exc:
        print(f"LỖI: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    run_cli()
