# CANVAS App - Development Journal

## Mục tiêu
Phần mềm tự động đăng nhập Kent State Canvas, tải toàn bộ nội dung về local,
và có khả năng hoàn thành bài tập với sự hỗ trợ của AI.

## Canvas URL
- Production: https://kent.instructure.com/
- Login flow: FlashLine SSO → username/password → MFA (optional) → Canvas

## Tech Stack
- **Python 3.11+**
- **Playwright** – browser automation, handle SSO login
- **canvasapi / requests** – gọi Canvas REST API sau khi có session
- **SQLite (sqlite3)** – lưu dữ liệu local
- **Claude API (anthropic)** – AI hoàn thành bài tập
- **Rich** – đẹp CLI output

## Cấu trúc thư mục
```
CANVAS/
├── CLAUDE.md               ← nhật ký này
├── main.py                 ← CLI entry point
├── requirements.txt
├── config.py               ← cấu hình (URL, paths)
├── .env                    ← credentials (KHÔNG commit)
├── auth/
│   ├── __init__.py
│   └── browser_auth.py     ← Playwright login FlashLine SSO
├── api/
│   ├── __init__.py
│   └── canvas_client.py    ← wrapper gọi Canvas API bằng session/token
├── sync/
│   ├── __init__.py
│   ├── courses.py          ← tải danh sách courses
│   ├── assignments.py      ← tải assignments + submissions
│   ├── files.py            ← tải files, pages, modules
│   └── modules.py          ← tải modules/content
├── agent/
│   ├── __init__.py
│   └── assignment_agent.py ← AI đọc đề, tạo câu trả lời
├── storage/
│   ├── __init__.py
│   └── database.py         ← SQLite operations
└── downloads/              ← files tải về lưu ở đây
```

## Cách chạy

### Setup lần đầu
```bash
cd /Users/khoihoang/Documents/CANVAS
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Điền credentials vào .env
```

### Chạy app
```bash
source venv/bin/activate   # activate venv trước

# Sync toàn bộ nội dung từ Canvas
python main.py sync

# Xem danh sách courses
python main.py list courses

# Xem assignments của một course
python main.py list assignments --course <course_id>

# Xem chi tiết một assignment
python main.py show assignment <assignment_id>

# AI hoàn thành một assignment (tạo draft để review)
python main.py complete <assignment_id>

# Submit assignment sau khi review
python main.py submit <assignment_id>
```

## Environment Variables (.env)
```
CANVAS_USERNAME=your_flashline_id
CANVAS_PASSWORD=your_password
ANTHROPIC_API_KEY=your_claude_api_key   # optional, dùng khi complete bài
```

## Login Flow (FlashLine SSO)
1. Mở https://kent.instructure.com/
2. Click nút Login (redirect sang FlashLine)
3. Điền FlashLine ID + Password
4. Nếu có MFA → app dừng lại, hỏi user nhập code
5. Sau login → extract cookies → dùng cho API calls

## MFA Handling
- App detect nếu có màn hình MFA
- In ra terminal: "Nhập MFA code:"
- User nhập → app tiếp tục
- Nếu không có MFA → tự động qua

## Canvas API Endpoints dùng
- GET /api/v1/courses → danh sách courses
- GET /api/v1/courses/:id/assignments → assignments
- GET /api/v1/courses/:id/files → files
- GET /api/v1/courses/:id/modules → modules
- GET /api/v1/courses/:id/pages → pages
- POST /api/v1/courses/:id/assignments/:id/submissions → submit bài

## Changelog

### 2026-04-02
- [x] Khởi tạo project structure
- [x] Tạo CLAUDE.md
- [x] Viết requirements.txt
- [x] Viết config.py
- [x] Viết auth/browser_auth.py (Playwright FlashLine SSO)
- [x] Viết api/canvas_client.py
- [x] Viết sync/ (courses, assignments, files, modules)
- [x] Viết storage/database.py
- [x] Viết agent/assignment_agent.py
- [x] Viết main.py CLI

## Issues / Notes
- Kent State dùng Shibboleth SSO, URL login thường là /login/saml
- Playwright chạy headless=False lần đầu để debug, sau đó có thể headless=True
- Session cookie của Canvas tên là `canvas_session`
- Sau khi login có thể lấy API token tự động từ profile page
