# Facebook scraper

Nếu đang học cách đọc mã nguồn, bắt đầu tại
[Hướng dẫn đọc code](docs/HUONG_DAN_DOC_CODE.md). Tài liệu giải thích luồng chương trình,
`async/await`, `yield`, Pydantic và phần JavaScript đọc giao diện.

Project chạy bằng Python trên Windows/PowerShell. Các lệnh bên dưới dành cho
workspace ngoài, có thư mục con `Demo_Fb_scraper`.
Nếu terminal đang ở cạnh main.py, bỏ tiền tố `Demo_Fb_scraper\` trong lệnh.

## Dùng giao diện (khuyên dùng)

Nhấp đúp **`Demo_Fb_scraper/start_ui.cmd`**, hoặc chạy từ workspace ngoài:

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py web --open
```

Giao diện mở tại **http://127.0.0.1:8765**. Giữ terminal đang chạy; đóng giao diện
bằng `Ctrl+C` tại terminal. Không cần cài thêm thư viện cho phần giao diện.
Nếu cổng bị dùng, thêm `--port 8766`.

`start_ui.cmd` tự mở Chrome bằng hồ sơ Facebook của project, với hai tab:
**Facebook** và **giao diện thu thập**. Dùng lại các tab đang có nếu đã mở. Phiên
đăng nhập đã lưu được giữ nguyên; nếu Facebook yêu cầu đăng nhập lại, thao tác
ngay trong tab Facebook rồi quay về tab giao diện. Không tự bắt đầu thu thập.

1. Chrome đã mở sẵn tab Facebook. Đăng nhập nếu cần. Nút **Mở Chrome đăng nhập**
   (hoặc **Đăng nhập Facebook** trên màn hình nhỏ) dùng để mở lại khi bạn đã đóng tab.
2. Giữ **Tự nhận diện**, nhập mỗi từ khóa hoặc URL Facebook trên một dòng. Có thể
   trộn từ khóa, URL cá nhân/Trang và URL nhóm trong cùng lượt; URL trùng được bỏ qua.
   Hoặc chọn riêng **Từ khóa**, **Cá nhân**, **Trang**, **Nhóm**.
3. Chọn số bài tối đa mỗi nguồn, số bình luận/reply mỗi bài, bật OCR nếu cần.
4. Bấm **Bắt đầu thu thập**. Theo dõi số nguồn đã xử lý, nhật ký và kết quả được lưu.
5. Bấm một bài để xem nội dung và luồng bình luận/reply. Có thể tìm trong kết quả,
   phân trang hoặc **Tải JSONL** trực tiếp từ SQLite.

**Dừng thu thập** hủy tác vụ hiện tại và xuất dữ liệu đã có. Chỉ một lượt được chạy
tại một thời điểm trong giao diện. Lịch sử lượt chạy được giữ trong phiên server;
bài viết tiếp tục nằm trong SQLite sau khi đóng giao diện. Các giới hạn nội dung
công khai của collector vẫn được áp dụng.

Giao diện chạy cục bộ để kết nối Chrome trên máy, dùng lại `.env`, `fb_profile/`
và `data/` hiện có. Không cần API key LLM để dùng giao diện. Lần đầu bật OCR có thể
cần tải model EasyOCR.

![Giao diện FB Collector](docs/ui-desktop.png)

## Cấu trúc

Mỗi file Python dưới **300 dòng**, tính cả dòng trống và chú thích.

```text
Demo_Fb_scraper/
├── main.py                  # Điểm chạy chung
├── .env                     # Cấu hình và API key (không commit)
├── .env.example             # Mẫu .env, sao chép thành .env
├── requirements.txt
├── start_ui.cmd             # Nhấp đúp để mở giao diện
├── README.md
├── fb_scraper/              # Mã nguồn ứng dụng
│   ├── browser/             # Hồ sơ và kết nối Chrome
│   │   ├── settings.py
│   │   ├── launcher.py
│   │   └── connection.py
│   ├── posts/               # Bài viết, bình luận, ảnh
│   │   ├── collector.py
│   │   ├── reader.py
│   │   ├── parser.py
│   │   ├── comments.py
│   │   ├── comment_reader.py # Đọc DOM bình luận và quan hệ reply
│   │   ├── labels.py        # Nhãn bình luận dùng chung Python/JS
│   │   └── pipeline.py
│   ├── entities/            # Thông tin cá nhân, Trang, nhóm
│   │   ├── collector.py
│   │   ├── reader.py
│   │   ├── parser.py
│   │   └── text.py
│   ├── search/              # Tìm đối tượng theo từ khóa
│   │   ├── collector.py
│   │   └── reader.py
│   ├── agent/               # Thu thập bằng LLM
│   │   └── mode.py
│   ├── web/                 # Giao diện localhost, API, worker và tài nguyên tĩnh
│   ├── storage/             # SQLite và xuất file
│   │   ├── database.py      # API lưu và xuất bốn bảng
│   │   ├── schema.sql       # sources/posts/comments/media và ràng buộc
│   │   ├── schema.py        # Khởi tạo và kiểm tra schema
│   │   ├── migration.py     # Sao lưu và chuyển dữ liệu cũ
│   │   ├── source_store.py  # Cá nhân/Trang/nhóm và metadata
│   │   ├── post_store.py    # Giao dịch lưu bài
│   │   ├── comment_store.py # Bình luận và FK reply
│   │   ├── media_store.py   # Media, SHA-256, OCR
│   │   ├── records.py       # Bản ghi chuẩn hóa và projection
│   │   ├── entity_store.py  # Adapter thông tin nguồn
│   │   ├── sql.py           # Chuyển dòng SQLite thành dictionary
│   │   ├── files.py         # Ghi file an toàn khi bị khóa
│   │   └── cli.py           # Lệnh storage
│   └── common/              # Thành phần dùng chung
│       ├── runtime.py       # UTF-8 terminal, nạp .env
│       ├── paths.py
│       ├── models.py
│       ├── comments.py       # Schema bình luận, tương thích và gộp theo ID
│       ├── urls.py
│       ├── numbers.py       # 1,2K -> 1200
│       ├── page_actions.py  # human_pause, expand_see_more
│       └── ocr.py
├── tests/                   # Kiểm thử và dữ liệu giả
├── scripts/                 # Công cụ hỗ trợ
│   ├── open_chrome.ps1
│   └── check_code_size.py
├── docs/
│   └── HUONG_DAN_DOC_CODE.md
├── data/                    # Database, snapshot, ảnh (không commit)
├── fb_profile/              # Hồ sơ Chrome giữ phiên Facebook (không commit)
└── .venv/                   # Môi trường Python (không commit)
```

Các thư mục Python có file `__init__.py` để Python nhận diện package.
File này chỉ mô tả thư mục, không chạy trình duyệt hay thu thập dữ liệu.

| Lệnh tại main.py | Phần xử lý |
| --- | --- |
| `posts` | `fb_scraper/posts/collector.py` |
| `entity` | `fb_scraper/entities/collector.py` |
| `search` | `fb_scraper/search/collector.py` |
| `agent` | `fb_scraper/agent/mode.py` |
| `browser` | `fb_scraper/browser/connection.py` |
| `storage` | `fb_scraper/storage/cli.py` |
| `web` | `fb_scraper/web/server.py` |

`main.py` chỉ chuyển lệnh và tùy chọn terminal tới CLI tương ứng.
Các module nghiệp vụ tiếp tục gọi hàm Python trực tiếp.
Dùng `main.py --help` để xem các lệnh, hoặc `main.py posts --help` để xem
tùy chọn thu thập bài viết. Các script Python phẳng trước đây đã được chuyển
vào các thư mục trên; hãy dùng các lệnh mới bên dưới.

`fb_scraper/common/paths.py` xác định thư mục gốc có `main.py`.
Cấu hình, database và hồ sơ Chrome tiếp tục nằm tại thư mục gốc này,
kể cả khi chạy lệnh từ terminal ở thư mục khác.

## Cài đặt

```powershell
python -m venv .\Demo_Fb_scraper\.venv
.\Demo_Fb_scraper\.venv\Scripts\python.exe -m pip install -r .\Demo_Fb_scraper\requirements.txt
Copy-Item .\Demo_Fb_scraper\.env.example .\Demo_Fb_scraper\.env
```

Điền API key vào `.env`. File `.env`, `fb_profile/`, `data/` và `.venv/` nằm
trong `.gitignore`: chúng chứa API key, cookie đăng nhập Facebook và dữ liệu đã
thu thập, nên không được commit.

## Hồ sơ Chrome riêng cho automation

Cấu hình mặc định trong `Demo_Fb_scraper/.env` (giống `.env.example`):

```dotenv
USE_SYSTEM_CHROME=0
USE_LOCAL_BROWSER=1
CHROME_USER_DATA_DIR=fb_profile
CHROME_PROFILE_DIRECTORY=Default
BROWSER_CDP_URL=http://127.0.0.1:9223
```

Cả collector và agent tự mở Chrome đã cài trên máy bằng hồ sơ cố định
`fb_profile/Default` cạnh `main.py`, hoặc dùng lại Chrome đó nếu nó đang chạy.
Chrome do project mở dùng CDP trên loopback, không dùng hộp thoại Allow của
chế độ kết nối Chrome cá nhân. Agent kết nối vào cùng Chrome qua CDP,
không tạo hồ sơ tạm hay sao chép hồ sơ.

### Thiết lập đăng nhập Facebook

Chạy một lần để mở hồ sơ riêng tại Facebook:

```powershell
powershell -ExecutionPolicy Bypass -File .\Demo_Fb_scraper\scripts\open_chrome.ps1
```

Đăng nhập Facebook trực tiếp trong cửa sổ này. **Không cần đăng nhập Gmail,
Google hoặc bật đồng bộ Chrome.** Nếu Facebook yêu cầu xác minh, xử lý bằng tay.
Sau khi đăng nhập xong, có thể đóng Chrome bình thường hoặc giữ cửa sổ mở.

Từ các lần sau, chạy thẳng lệnh collector/agent bên dưới. Project tự mở Chrome,
kiểm tra đường dẫn hồ sơ thực tế rồi bắt đầu thu thập. Không cần chạy script
mở Chrome trước mỗi lượt. Nếu chưa đăng nhập, collector có thể dừng hoặc báo
`login_required`; hãy chạy script thiết lập, đăng nhập rồi chạy lại collector.

Phiên Facebook được lưu trong thư mục hồ sơ trên ổ đĩa và thường vẫn còn sau
khi tắt/bật máy. Cần đăng nhập lại khi phiên hết hạn, Facebook yêu cầu xác minh,
bạn đăng xuất hoặc dữ liệu hồ sơ bị xóa. Project không đảm bảo phiên tồn tại
vĩnh viễn và không tự xử lý captcha/checkpoint.
Không xóa `fb_profile` nếu muốn giữ phiên đăng nhập.

### Cấu hình và vòng đời Chrome

Đường dẫn `CHROME_USER_DATA_DIR` tương đối luôn tính từ thư mục có `main.py`,
kể cả khi chạy từ workspace ngoài hoặc Windows Task Scheduler.
Để dùng thư mục khác, đặt đường dẫn tuyệt đối; để chọn Chrome đã cài ở nơi khác,
đặt `CHROME_EXECUTABLE` đến `chrome.exe`.
Launcher PowerShell và Python dùng cùng cấu hình.
Biến môi trường tiến trình được ưu tiên hơn `.env`; file `.env` cạnh `main.py`
được ưu tiên hơn `.venv/.env`.

Cổng mặc định của chế độ hồ sơ riêng là `127.0.0.1:9223`.
Nếu cổng bị ứng dụng khác chiếm, project báo lỗi; không tự đóng ứng dụng đó.
Nếu hồ sơ này đang được mở thủ công mà không có CDP, đóng cửa sổ của hồ sơ đó
rồi để project mở lại.
Chỉ chạy một lượt điều khiển trên cùng hồ sơ tại một thời điểm.

Sau kết nối, project mở tab chẩn đoán `chrome://version` để đối chiếu đường dẫn
hồ sơ thật. Nếu không khớp, dừng trước khi thu thập. Tab chẩn đoán được đóng;
các tab của collector được đóng khi hoàn tất, còn Chrome và hồ sơ được giữ.
Project không tắt Chrome cá nhân.

### Các chế độ kết nối khác

- `USE_SYSTEM_CHROME=1`: kết nối Chrome cá nhân đã mở; cần cấu hình đúng User Data
  và hồ sơ (ví dụ Profile 2), bật Remote debugging và bấm Allow. Chế độ này được
  ưu tiên nếu cả hai cờ đều bật.
- Cả hai cờ bằng `0`: kết nối Chrome CDP do bạn mở trước tại `BROWSER_CDP_URL`
  (mặc định `http://localhost:9222` khi không cấu hình).
- Lỗi kết nối không tự chuyển sang hồ sơ trắng.

Tham khảo [Chrome về thư mục riêng cho remote debugging](https://developer.chrome.com/blog/remote-debugging-port)
và [cơ chế xác nhận khi kết nối Chrome cá nhân](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session).

## Thu thập bài viết

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py posts --max-posts 20 --comments 20
```

Đổi từ khóa ngay trên dòng lệnh, nhập tiếng Việt bình thường; chương trình tự
encode URL, không cần sửa URL trong code:

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py posts --keyword "việc làm online tại nhà" --max-posts 20 --comments 5
```

Có thể lặp `--keyword "từ khóa khác"` để tìm nhiều từ khóa; `--max-posts` áp dụng
cho mỗi từ khóa. Khi có `--keyword`, chỉ tìm các từ khóa được truyền vào.
Khi không truyền, dùng danh sách `KEYWORDS` trong `fb_scraper/posts/collector.py`
(hiện là `việc làm online tại nhà`); danh sách này cũng chỉ cần nhập chữ thường.
`--ocr` bật OCR ảnh; `--gpu` chọn GPU cho OCR.
Collector bổ sung bình luận cho bài đã có khi chưa đạt số lượng yêu cầu hoặc còn thiếu ID/quan hệ/tên người viết, giữ
ảnh/OCR đã lưu. URL tìm kiếm không được dùng làm permalink; các URL
`/share/p/`, `story_fbid`, `fbid` và `v` được xử lý riêng.

Collector mở các nút **Xem thêm/See more** trước khi đọc, chờ nội dung tải xong và
đọc lại reply vừa được tải. Nếu thẻ bài vẫn bị thu gọn, thử đọc đúng permalink trong
tab phụ. Khi thu thập lại bài đã có, tên người viết và nội dung đầy đủ được cập nhật;
bản rút gọn không ghi đè bản đầy đủ. Danh sách kết quả và cửa sổ chi tiết hiển thị
toàn bộ nội dung đã lưu, không giới hạn ở hai dòng.

### Cấu trúc bình luận và reply

`top_comments` là DTO trung gian của collector. Các trường chính gồm:

| Trường | Ý nghĩa |
| --- | --- |
| `comment_id` | ID riêng của bình luận/reply, không phải ID của bình luận gốc |
| `parent_comment_id` | ID cha trực tiếp khi xác định được từ DOM |
| `root_comment_id` | ID bình luận gốc của luồng |
| `is_reply` | `false`: bình luận gốc; `true`: reply; `null`: chưa xác định |
| `author` | Tên người viết hiển thị |
| `author_url` | URL người viết khi có |
| `text` | Nội dung riêng của bình luận, không ghép các reply con |
| `url` | Permalink bình luận, giữ `comment_id` và `reply_comment_id` |
| `posted_raw` | Thời gian hiển thị trên permalink nếu có |

Ví dụ rút gọn một luồng có reply hai cấp:

```json
"top_comments": [
  {"comment_id": "100", "parent_comment_id": null, "root_comment_id": "100", "is_reply": false, "author": "A", "text": "Cho mình hỏi thông tin"},
  {"comment_id": "101", "parent_comment_id": "100", "root_comment_id": "100", "is_reply": true, "author": "B", "text": "Bạn muốn hỏi gì?"},
  {"comment_id": "102", "parent_comment_id": "101", "root_comment_id": "100", "is_reply": true, "author": "A", "text": "Lịch làm việc thế nào?"}
]
```

Trong DTO, `post_id`/`comment_id` là khóa Facebook. SQLite lưu bình luận ở bảng
`comments`: `post_id` tham chiếu ID số của `posts`, `parent_comment_id` tham chiếu
ID số của `comments`. Khóa Facebook nằm ở `post_key`/`comment_key`.
Xem [schema và ví dụ JOIN](docs/DATABASE_SCHEMA.md) để phân biệt hai loại định danh.
Khi chỉ có permalink cho biết gốc luồng mà không biết cha trực tiếp,
`parent_comment_id` để `null`; không suy ra quan hệ từ tên người được nhắc trong text.

`--comments` giới hạn tổng bản ghi đọc trong mỗi lượt cho mỗi bài, gồm cả reply.
Collector mở nút xem reply trước khi kiểm tra giới hạn. Khi bổ sung cho bài đã có,
các bản ghi cũ được giữ, nên tổng tích lũy có thể lớn hơn giới hạn của một lượt.
Cùng nội dung nhưng ID khác nhau vẫn được lưu riêng; cùng ID được cập nhật.
ID số và global ID base64 dạng `comment:<post>_<comment>` được đối chiếu về cùng ID
bình luận để cập nhật dữ liệu cũ mà không tạo bản ghi trùng.

Dữ liệu chuỗi cũ vẫn đọc được và khi xuất sẽ thành object giữ nguyên `text`, các
trường ID/quan hệ chưa biết để `null`. Chạy lại collector với `--comments` lớn hơn 0
để đọc lại metadata/tên/nội dung còn bị rút gọn, kể cả khi danh sách cũ đã đủ số lượng. Không thể khôi phục
chính xác quan hệ reply chỉ từ chuỗi đã lưu; nội dung cũ được giữ nếu chưa đối chiếu được.

## Cá nhân/Trang và nhóm

```powershell
# Chỉ lấy thông tin Giới thiệu của cá nhân/Trang
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py entity "https://www.facebook.com/zuck" --type profile --info-only

# Thu thập một Trang cụ thể và lưu source_type=page
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py entity "https://www.facebook.com/ten.trang" --type page --max-posts 5 --comments 10

# Chỉ lấy thông tin nhóm
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py entity "https://www.facebook.com/groups/pythonvietnam" --type group --info-only

# Lấy thông tin, tối đa 5 bài và 20 bình luận mỗi bài của nhóm công khai
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py entity "https://www.facebook.com/groups/pythonvietnam" --type group --max-posts 5 --comments 20
```

Có thể truyền nhiều URL cùng loại, ngăn cách bằng khoảng trắng.
`--info-only` hoặc `--max-posts 0` chỉ lấy thông tin; mặc định lấy tối đa
20 bài mỗi nguồn. Chỉ lấy bài nhóm xác định là công khai; bài cá nhân cần có
nhãn chia sẻ công khai. Project không tham gia nhóm, không lấy danh sách thành
viên và không lưu ngày sinh/điện thoại/email từ phần Giới thiệu.

Thông tin profile gồm tên, URL, ID nếu có, loại tài khoản khi hiển thị, tiểu sử,
người theo dõi, công việc, học vấn và nơi sống. Nhóm gồm tên, URL, ID nếu có,
mô tả, công khai/riêng tư, số thành viên và quy tắc nếu hiển thị.
Các trạng thái `ok`, `partial`, `unavailable`, `login_required` phản ánh khả năng
đọc trang; trường không thấy để `null`. Username dùng khóa `u_...`, không giả
thành ID số của Facebook.

## Tìm kiếm theo từ khóa

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py search "Python Việt Nam" --type group --max-results 20
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py search "messi" --type both --max-results 10
```

`--type` nhận `profile`, `group`, `both` (mặc định).
Có thể truyền nhiều từ khóa. Giới hạn kết quả áp dụng cho mỗi từ khóa và mỗi
loại; `--max-results 0` lấy đến giới hạn cuộn. `--max-scrolls` mặc định 30,
dừng sau 4 lượt không có URL mới. Facebook quyết định kết quả được hiển thị.

Mỗi URL được đọc thông tin một lần trong lượt chạy dù xuất hiện ở nhiều từ khóa.
Nhật ký tìm kiếm giữ từng lần phát hiện, kể cả URL lặp. Tìm kiếm luôn chuyển
sang chế độ chỉ đọc thông tin Giới thiệu. Kết nối Chrome và SQLite được dùng
chung xuyên suốt, không parse argparse hay kết nối CDP lại cho từng loại.

## Chế độ agent

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py agent "https://www.facebook.com/search/posts?q=messi" --max-posts 5 --max-steps 80
```

Cấu hình provider/model/API key trong `.env`. Agent lưu ngay từng bài vào
SQLite bằng action `save_fb_post`; các bài đã commit được giữ khi LLM gặp lỗi.
Agent lưu URL ảnh; dùng DOM collector để tải ảnh. Cả hai dùng schema
`Post` chung với các trường `images` và `links`; vẫn chấp nhận tên đầu vào cũ
`image_urls` và `external_links`.
Kết nối agent dùng `keep_alive=True`; kết thúc chỉ ngắt kết nối điều khiển.

## Lưu trữ và khôi phục

Dữ liệu luôn ở `data` cạnh `main.py`, kể cả khi chạy từ thư mục khác.

- `posts.db`: SQLite, dữ liệu gốc; commit ngay sau từng bài/đối tượng/kết quả tìm kiếm.
- `sources.jsonl`, `posts.jsonl`, `comments.jsonl`, `media.jsonl`: snapshot của bốn bảng.
- `data_agent.json`: các bài thu được trong lượt chạy agent.
- `images`: ảnh do DOM collector tải.

JSON/JSONL được xuất **khi lượt chạy kết thúc**, kể cả qua nhánh xử lý lỗi hoặc
ngắt thông thường. Không query và ghi đè toàn bộ JSONL sau mỗi lần bổ sung
text/comment/ảnh/OCR. Nếu tiến trình bị tắt cưỡng bức, SQLite giữ những lần
commit trước đó; chạy lệnh xuất lại để cập nhật snapshot.

SQLite dùng bốn bảng quan hệ. Bình luận và media không còn là danh sách JSON trong
cột posts. JSONL giữ đúng ID/khóa ngoại; mỗi dòng posts bổ sung nguồn, bình luận và
media liên quan. Cập nhật từng phần giữ các trường đã có khi caller bỏ qua chúng.
Tên người viết, URL và metadata bổ sung vẫn được giữ. Chi tiết tại
[DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md).

Lần đầu nâng cấp, project sao lưu `posts.before-v3-<mã>.db` trước khi chuyển schema.
Thông tin profiles/groups và lịch sử tìm kiếm chuyển vào metadata của sources;
bình luận/ảnh/OCR chuyển sang comments/media trong một transaction. Nếu lỗi,
rollback và giữ database cũ. Các snapshot cũ được giữ để đối chiếu, không cập nhật nữa.

Khi file xuất bị Windows khóa, storage thử lại rồi giữ snapshot mới ở
`*.pending.jsonl`/`*.pending.json`. Nếu bản pending cũng bị khóa, giữ file tạm
duy nhất được in trong log. Lỗi xuất không rollback dữ liệu SQLite.

Xuất lại bốn file JSONL mà không chạy Chrome/LLM:

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\main.py storage --export-jsonl
```

Bản JSON riêng của lượt agent bị khóa có thể đọc từ `data_agent.pending.json`;
bài viết của lượt đó cũng đã nằm trong SQLite.

## Kiểm thử

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s .\Demo_Fb_scraper\tests -t .\Demo_Fb_scraper -p "test_*.py" -v
```

Kiểm thử dùng database tạm và browser/LLM giả: khóa file Windows, phục hồi khi
ngắt, migration dữ liệu cũ, số lần xuất snapshot, chia sẻ kết nối khi tìm kiếm
và từ chối hồ sơ Chrome không khớp. Không thu thập Facebook hoặc gọi API LLM.
Kiểm tra predicate JavaScript được bỏ qua khi máy chưa có Node. Có thể dùng Node
đi kèm Playwright bằng cách thêm `.venv\Lib\site-packages\playwright\driver`
vào `PATH` trước khi chạy test.

`test_comment_dom.py` chạy thêm Chrome headless trên HTML cục bộ để kiểm tra ID,
reply nhiều cấp và tách nội dung cha/con; bỏ qua nếu không tìm thấy Chrome.
Các kiểm thử này dùng hồ sơ tạm, không truy cập Facebook hoặc gọi LLM.

Kiểm tra giới hạn độ dài trong main.py, fb_scraper/, tests/ và scripts/:

```powershell
.\Demo_Fb_scraper\.venv\Scripts\python.exe .\Demo_Fb_scraper\scripts\check_code_size.py
```

Script in số dòng từng file và trả mã lỗi nếu có file từ 300 dòng trở lên.
Thư viện trong `.venv` và dữ liệu hồ sơ Chrome không thuộc mã nguồn project.
