# CANVAS Web App - Multi-User Dashboard

## Overview
A Flask-based web application for Kent State Canvas automation:
- **Google OAuth** login for user authentication
- **Canvas credential linking** (1:1 relationship with FlashLine account)
- **Automatic data sync** from Canvas (modules, assignments, files, pages)
- **AI-powered assignment help** using Claude API
- **Quiz solving** using GPT-4o Vision for image analysis
- **PostgreSQL** for multi-user data isolation
- **Deployed on Railway** for public access

## Tech Stack
- **Backend**: Python 3.9+, Flask 3.1, Gunicorn
- **Database**: PostgreSQL (Supabase), psycopg2
- **Browser Automation**: Playwright 1.44
- **Authentication**: Google OAuth (authlib), Fernet encryption for Canvas passwords
- **APIs**: Anthropic (Claude), OpenAI (GPT-4o), Canvas REST API
- **Frontend**: Jinja2, Tailwind CSS, Vanilla JavaScript
- **Deployment**: Docker, Railway

## Project Structure
```
CANVAS/
├── CLAUDE.md                      # This file
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container image
├── railway.toml                   # Railway deployment config
├── config.py                      # Configuration & paths
├── .env.example                   # Environment variables template
│
├── web/
│   ├── app.py                     # Flask app (724 lines)
│   ├── admin.py                   # Admin panel blueprint
│   └── templates/
│       ├── base.html              # Base layout
│       ├── login.html             # Google OAuth login
│       ├── setup_canvas.html      # Canvas credential setup
│       ├── dashboard.html         # Course grid
│       ├── course.html            # Course modules/assignments
│       ├── assignment.html        # Assignment detail + AI helper
│       ├── page_view.html         # Canvas page viewer
│       └── admin/                 # Admin templates
│
├── auth/
│   └── browser_auth.py            # Playwright Canvas login (refactored)
│
├── api/
│   └── canvas_client.py           # Canvas API wrapper
│
├── sync/
│   ├── courses.py                 # Fetch courses
│   ├── assignments.py             # Fetch assignments & submissions
│   ├── files.py                   # Download files & PDFs
│   ├── modules.py                 # Fetch module content
│   ├── pages_deep.py              # Fetch page content
│   └── organizer.py               # Build local folder structure
│
├── agent/
│   ├── assignment_agent.py        # Claude AI assignment helper
│   └── quiz_agent.py              # GPT-4o quiz solver
│
└── storage/
    ├── database.py                # PostgreSQL operations
    └── users.py                   # User account management
```

## User Flow

### 1. Google OAuth Login
- User clicks "Login with Google"
- Redirected to Google account selection
- Callback creates/updates user in `users` table
- Session stores `google_id`

### 2. Canvas Account Setup (One-time)
- If `canvas_linked=0`, user shown setup form
- Enters FlashLine ID & password
- Credentials encrypted with Fernet (key derived from `FLASK_SECRET_KEY`)
- Stored in `users.canvas_user` & `users.canvas_pass` (BYTEA)
- Sets `canvas_linked=1`

### 3. Data Sync (On-demand)
- User clicks "Sync Canvas" button
- Background thread calls `login()` with Canvas credentials
- Playwright opens Canvas, clicks FlashLine login, fills Microsoft OAuth form
- Extracts session cookies + API token
- Downloads all courses, assignments, files, modules, pages
- Data stored in PostgreSQL with `google_id` isolation
- UI polls `/api/sync_status` for real-time progress

### 4. Dashboard
- Shows all courses as cards (with color-coded badges)
- Per-course: assignment count, pending submissions count
- Click course → view modules and assignments

### 5. Assignment Help
- Click assignment → shows details + AI helper panel
- Claude reads assignment, generates draft response
- User can edit before submitting to Canvas

### 6. Quiz Solving
- Click quiz → Playwright opens in headless browser
- Extracts questions + images from DOM
- Sends to GPT-4o Vision for analysis
- Shows recommended answers

## Database Schema

### users (users.py)
```
google_id (PK TEXT)
├── email TEXT UNIQUE
├── name, picture TEXT
├── canvas_user, canvas_pass (BYTEA, encrypted)
├── canvas_linked INTEGER (0/1)
├── is_admin, is_banned INTEGER
├── sync_status TEXT ('syncing:msg', 'done', 'error:msg')
├── sync_at TEXT (ISO timestamp)
└── created_at TEXT (ISO timestamp)
```

### user_sessions
```
google_id (PK, FK)
├── cookies_json TEXT (JSON array)
├── api_token TEXT
└── updated_at TEXT
```

### courses (database.py)
```
google_id (PK), id (PK BIGINT)
├── name, course_code TEXT
├── enrollment_term_id BIGINT
├── workflow_state TEXT
└── raw JSONB (full Canvas object)
```

### assignments
```
google_id (PK), id (PK BIGINT)
├── course_id, name, description TEXT
├── due_at TEXT, points_possible REAL
├── submission_types TEXT (JSON array)
├── has_submitted_submissions INTEGER
└── raw JSONB
```

### submissions, files, modules, module_items, pages
Similar structure with `google_id` composite keys for user isolation.

## Environment Variables

**Required for Railway deployment:**
```
GOOGLE_CLIENT_ID=...              # From Google Cloud Console
GOOGLE_CLIENT_SECRET=...          # From Google Cloud Console
DATABASE_URL=postgresql://...     # Supabase PostgreSQL
FLASK_SECRET_KEY=...              # Can be auto-generated, but set for consistency
OPENAI_API_KEY=...                # For GPT-4o quiz solving
```

**Optional:**
```
ANTHROPIC_API_KEY=...             # For Claude assignment help
ADMIN_PASSWORD=...                # Admin panel password
HEADLESS_BROWSER=true             # For Railway headless mode
```

## Deployment Steps

### Local Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with local values
export DATABASE_URL="postgresql://localhost/canvas_local"
flask run
```

### Railway Deployment
```bash
# 1. Push to GitHub (auto-deploys)
git add -A
git commit -m "Ready for production"
git push origin main

# 2. Set environment variables in Railway dashboard:
#    - GOOGLE_CLIENT_ID
#    - GOOGLE_CLIENT_SECRET
#    - DATABASE_URL (Supabase PostgreSQL)
#    - FLASK_SECRET_KEY (secrets.token_hex(32))
#    - OPENAI_API_KEY (for quiz solving)

# 3. Connect GitHub repo to Railway project
# 4. Railway auto-builds Docker image and deploys

# Your app is now live at: https://[project]-[environment].up.railway.app
```

## Canvas Login Troubleshooting

The app uses Playwright to automate Canvas login via FlashLine SSO → Microsoft OAuth. This is complex and can fail if:

### Possible Issues:
1. **Wrong FlashLine credentials** - User enters invalid username/password
2. **MFA required** - Microsoft requires 2FA code (app will prompt)
3. **Microsoft page structure changed** - Selectors may not match new HTML
4. **Browser detection** - Microsoft detects headless browser as bot
5. **Network timeouts** - Railway container network issues

### Debug Steps:
1. Check Railway logs for detailed error messages
2. Look for screenshots: `data/login_failure.png`
3. Check `data/ms_email_page.png`, `data/ms_password_page.png`
4. Verify Canvas account is not locked (too many login attempts)

### If Login Fails:
The app falls back to using only session cookies (no API token). Data sync will still work, but some features may be limited.

## Key Improvements Made

### Refactored browser_auth.py
- Simplified form filling logic (removed complex fallbacks)
- Uses Microsoft's official selector IDs (#idSIButton9, #i0116, #i0118)
- Better error messages showing exactly what failed
- Multiple submission methods: click → Enter → JavaScript
- Faster execution with `domcontentloaded` instead of `networkidle`

### Database Design
- PostgreSQL with Supabase for reliability
- Composite primary keys `(google_id, id)` for data isolation
- Per-user encryption of Canvas password
- Thread-local context for request-scoped user isolation

### Security
- Fernet encryption for Canvas passwords (key from FLASK_SECRET_KEY)
- Session-based auth, no per-request DB calls (avoids timeout issues)
- SQL parameter binding (psycopg2 auto-escapes %)
- Google OAuth with proper token validation
- Per-user file downloads to isolated directories

### Performance
- Background thread for long-running sync task
- Real-time progress polling via JavaScript
- Efficient database queries with proper indexing
- Cached API responses where possible

## Common Issues & Solutions

### "UndefinedTable: relation 'courses' does not exist"
**Solution:** `init_db()` called at startup to create tables

### "Login failed at URL: https://login.microsoftonline.com/..."
**Solution:** Microsoft SSO form submission failed. Check credentials, check logs.

### "No Canvas credentials saved"
**Solution:** User hasn't completed `/setup/canvas` yet. They're seeing empty dashboard.

### "Connection timeout"
**Solution:** Supabase connection timeout. Added `connect_timeout=5` and simplified per-request DB calls.

### "InvalidToken() when decrypting password"
**Solution:** Fernet key changed (was file-based). Now derived from `FLASK_SECRET_KEY`.

## Future Improvements

- [ ] Cache Canvas API responses to reduce load
- [ ] Add webhook for real-time assignment updates
- [ ] Support multiple Canvas instances (not just Kent)
- [ ] Offline mode with data sync when back online
- [ ] Batch assignment submission
- [ ] Grade prediction based on submissions

## Monitoring

Monitor these Railway metrics:
- **Restart count**: Should be 0 (container stability)
- **CPU/Memory**: Should be <100MB memory, <10% CPU
- **Error rate**: Check logs for sync failures, login errors
- **Active users**: Number of concurrent sessions

## Support

For issues:
1. Check Railway logs: `railway logs`
2. Check screenshots in app data directory
3. Review error messages in dashboard UI
4. Check GitHub issues (if public)
