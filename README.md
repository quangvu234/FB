# OSINT — Facebook Collector

Project Python có giao diện thu thập bài viết Facebook theo từ khóa, cá nhân,
Trang và nhóm công khai; lưu SQLite với bốn bảng `sources`, `posts`, `comments`, `media`.

- [Hướng dẫn cài đặt và sử dụng](Demo_Fb_scraper/README.md)
- [Schema database và ví dụ SQL JOIN](Demo_Fb_scraper/docs/DATABASE_SCHEMA.md)
- [Hướng dẫn đọc mã nguồn](Demo_Fb_scraper/docs/HUONG_DAN_DOC_CODE.md)

Sau khi cài môi trường theo hướng dẫn, mở giao diện bằng:

```powershell
.\Demo_Fb_scraper\start_ui.cmd
```

Chrome sẽ mở tab Facebook và giao diện tại `http://127.0.0.1:8765`.
API key, hồ sơ Chrome, dữ liệu thu thập và log được loại khỏi mã nguồn bằng `.gitignore`.
