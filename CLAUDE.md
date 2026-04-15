# CANVAS App - Browser Extension Architecture

## Status: Phase 4 Complete - Browser Extension MVP

**Updated**: 2026-04-15 (Phase 4 Complete)
**Current Phase**: 4/6 ✅ Complete
**Next Phase**: 5 - Integration Testing & Deployment

---

## 🔄 MAJOR PIVOT: Why Extension Architecture?

### Previous Approach (Deprecated)
- ❌ Relied on users providing Canvas API tokens
- ❌ Unrealistic in practice - users don't have tokens
- ❌ Attempted server-side Playwright login (fragile, risky)
- ❌ No way to scale to multiple Canvas instances

### New Approach (CURRENT)
- ✅ Browser extension reads assignment from user's Canvas session
- ✅ No credentials needed - extension runs where user already logged in
- ✅ Reliable - uses real browser session, not automation
- ✅ Scalable to any Canvas instance without setup
- ✅ Secure - no server-side password/credential storage

---

## 📐 Architecture Overview

```
User's Canvas Session (in browser)
        ↓ Extension reads page
        ↓
   Extract assignment data
   (title, description, context)
        ↓
   Send to Backend API
        ↓
Backend: Validate auth token
   ↓
Call Claude AI with context
   ↓
Save draft to database
   ↓
Return draft to extension/web app
        ↓
User copies draft and submits manually to Canvas
```

---

## 🚀 PHASE 1: COMPLETE ✅

### What Was Done
- ✅ Created `ai_completions` table (stores AI-generated drafts)
- ✅ Created `extension_auth_tokens` table (stores extension auth tokens)
- ✅ Removed `canvas_api_token` column from users table
- ✅ Removed `canvas_linked` column from users table
- ✅ Marked old Canvas tables as deprecated (NOT deleted, kept for reference)
- ✅ Added database functions: save_ai_completion, get_user_completions, delete_completion
- ✅ Added storage functions: generate_extension_auth_token, verify_extension_auth_token
- ✅ Created migration script (idempotent, reversible)
- ✅ Migration tested and verified successfully

### Migration Approach
- Old Canvas tables remain in database (marked deprecated)
- Zero data loss - all existing user accounts preserved
- Can safely test extension code without deleting legacy data
- Tables can be removed later after full extension rollout

### Files Modified
- `storage/database.py` - Added new tables, helper functions
- `storage/users.py` - Added extension auth functions
- `migrate_to_extension.py` - New migration script

---

## 🎯 MVP Scope

### ✅ INCLUDE IN MVP
- Assignment help (generate draft from title + description + context)
- Draft history (list, view, delete saved drafts)
- Google OAuth login for user account
- Extension auth token management
- API for assignment context submission
- AI draft generation and storage

### ❌ NOT IN MVP (v1.1+)
- Quiz automation (too complex, save for later)
- Auto-submit to Canvas (just copy/paste for now)
- Multiple Canvas instances (Kent State focus)
- Subscription/billing
- Offline support

---

## 🛠️ Implementation Plan

### Phase 1: Database Schema ✅ COMPLETE
**Status**: ✅ Done (1.5 hours)

Completed:
- ✅ Added `ai_completions` table 
- ✅ Added `extension_auth_tokens` table
- ✅ Removed Canvas token columns from users
- ✅ Marked old tables as deprecated (kept them)
- ✅ Created helper functions
- ✅ Tested migration script

### Phase 2: Backend API ✅ COMPLETE
**Status**: ✅ Done (2.5 hours)

Completed:
- ✅ Implemented `POST /api/auth/extension` (generate extension auth token)
- ✅ Implemented `POST /api/assignment/complete` (receive context, return AI draft)
- ✅ Implemented `GET /api/completions` (paginated list of user's drafts)
- ✅ Implemented `GET /api/completions/{id}` (view full draft with ownership check)
- ✅ Implemented `DELETE /api/completions/{id}` (delete draft with ownership check)
- ✅ Added `extension_auth_required` decorator for token validation
- ✅ Refactored `assignment_agent.py` with `complete_assignment_from_context()` function
- ✅ All endpoints properly handle user context and activity tracking

**New Endpoints**:
```
POST   /api/auth/extension              → Generate extension token (requires Google login)
POST   /api/assignment/complete         → Submit assignment context, get AI draft
GET    /api/completions                 → List user's drafts (paginated)
GET    /api/completions/{id}            → View specific draft
DELETE /api/completions/{id}            → Delete draft
```

**Authentication**: All new endpoints use extension token validation via `extension_auth_required` decorator

### Phase 3: Web App UI ✅ COMPLETE
**Status**: ✅ Done (2 hours)

Completed:
- ✅ Refactored `/` dashboard to show recent AI drafts instead of Canvas courses
- ✅ Created `/settings` page (extension token setup with instructions)
- ✅ Created `/drafts` page (full draft history with search, filter, pagination)
- ✅ Updated navigation bar (added Settings link)
- ✅ Removed Canvas token entry requirements
- ✅ Updated dashboard route to fetch and display ai_completions
- ✅ Added statistics (total drafts, this week's count)

**New Pages**:
```
GET    /                               → Dashboard (recent AI drafts)
GET    /settings                       → Extension setup (show token, instructions)
GET    /drafts                         → Full draft history (search, filter, pagination)
```

**Deprecated but Kept**:
- Canvas token setup (still works, not linked from nav)
- Course browsing pages (still accessible)
- Assignment viewer (still accessible)

### Phase 4: Browser Extension MVP ✅ COMPLETE
**Status**: ✅ Done (4 hours)

Completed:
- ✅ Created Manifest V3 extension structure
- ✅ Built popup UI for draft display and interaction
- ✅ Created content script to read Canvas assignment pages
- ✅ Implemented auth token storage and management
- ✅ Added API communication with backend
- ✅ Created settings page for token configuration
- ✅ Implemented token validation and error handling
- ✅ Added draft copying to clipboard functionality

**Extension Files**:
```
extension/
├── manifest.json         ← Manifest V3 config
├── popup.html            ← Draft popup UI
├── settings.html         ← Settings/options page
├── js/
│   ├── popup.js         ← Popup logic + API calls
│   ├── content.js       ← Canvas page DOM reading
│   ├── background.js    ← Service worker + storage
│   └── settings.js      ← Settings management
├── css/
│   ├── popup.css        ← Popup styling
│   └── settings.css     ← Settings styling
└── README.md            ← Installation & usage guide
```

**How It Works**:
1. User visits Canvas assignment page
2. Extension icon appears in toolbar
3. User clicks icon → popup loads
4. Content script extracts assignment data (title, description)
5. Popup sends to `/api/assignment/complete` with auth token
6. Backend returns AI draft
7. User can copy draft or view full version
8. All drafts saved to account history

### Phase 5: Testing (2 hours)
- Test extension reads page correctly
- Test backend receives data
- Test AI generates draft
- Test auth flow works

### Phase 6: Deployment (1 hour)
- Deploy to Railway
- Update environment variables
- Test end-to-end

**Total Time**: ~14-15 hours focused development

---

## 📊 What's Being Reused vs Removed

### ✅ KEEP & REFACTOR
```
config.py (100%)                 → Keep all env vars
storage/users.py (70%)           → Keep user auth, remove canvas tokens
agent/assignment_agent.py (60%)  → Refactor to accept context param
storage/database.py (40%)        → Remove Canvas tables, add completions
tasks/cleanup.py (90%)           → Remove Canvas table cleanup
web/app.py (40%)                 → Keep OAuth, remove sync/setup
```

### ❌ DELETE
```
sync/*                  → Entire folder (no server sync)
auth/browser_auth.py    → Playwright login not needed
api/canvas_client.py    → No Canvas API from backend
```

### 📈 Result
- Remove: ~300 lines of dead code
- Keep: ~800 lines of core logic  
- Add: ~600 lines of extension APIs
- Net: ~+300 lines (smaller, focused)

---

## 🔐 Authentication Flow

### How Extension Proves Identity
1. User logs into web app (Google OAuth)
2. Web app generates `extension_auth_token` (random 32 chars)
3. Web app displays token in `/settings`
4. User copies token from settings
5. User opens extension, goes to Options
6. User pastes token into extension storage
7. Extension stores locally
8. Extension includes token in every API request
9. Backend verifies token → google_id mapping

### Why This Works
- Simple to implement
- User explicitly approves extension
- No Canvas API token needed
- Token can be regenerated anytime
- Token-based auth is proven pattern

---

## 💾 Database Changes

### REMOVE Tables
```sql
courses, assignments, submissions, files,
pages, modules, module_items, user_sessions
```

### ADD Tables
```sql
CREATE TABLE ai_completions (
  id SERIAL PRIMARY KEY,
  google_id TEXT NOT NULL,
  course_id INT,
  assignment_id INT,
  assignment_title VARCHAR(500),
  assignment_description TEXT,
  context_summary TEXT,
  ai_draft TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  FOREIGN KEY (google_id) REFERENCES users(google_id)
);

CREATE TABLE extension_auth_tokens (
  id SERIAL PRIMARY KEY,
  google_id TEXT NOT NULL UNIQUE,
  auth_token VARCHAR(64) NOT NULL UNIQUE,
  created_at TIMESTAMP,
  last_used_at TIMESTAMP,
  FOREIGN KEY (google_id) REFERENCES users(google_id)
);
```

### MODIFY users Table
```sql
ALTER TABLE users DROP COLUMN canvas_api_token;
ALTER TABLE users DROP COLUMN canvas_linked;
-- KEEP: google_id, email, name, picture, is_admin, is_banned,
--       last_accessed_at, created_at
```

---

## 🌐 New API Endpoints

### `POST /api/auth/extension`
Generate or verify extension auth token
```
Request: {"user_id": "google_xxx", "action": "generate"}
Response: {"auth_token": "ext_xxx..."}
```

### `POST /api/assignment/complete`
Get AI-generated draft for assignment
```
Request: {
  "auth_token": "ext_xxx",
  "course_id": 123,
  "assignment_id": 456,
  "assignment_title": "...",
  "assignment_description": "...",
  "context": "..."
}
Response: {
  "success": true,
  "draft_id": 789,
  "ai_draft": "Generated response..."
}
```

### `GET /api/completions`
List user's saved AI drafts
```
Response: {
  "completions": [
    {"id": 789, "assignment_title": "...", "created_at": "..."}
  ]
}
```

### Other Endpoints
- `GET /api/completions/{id}` - get full draft
- `DELETE /api/completions/{id}` - delete draft

---

## 🧩 Browser Extension MVP

### What Extension Does
1. Detects when user visits Canvas assignment page
2. Reads assignment DOM to extract:
   - Title
   - Description
   - Links to course materials
3. Shows "Get AI Help" button
4. Sends assignment + context to backend
5. Displays draft in popup
6. Provides copy-to-clipboard

### What Extension Does NOT Do (Yet)
- Auto-fill Canvas form
- Submit assignment
- Access Canvas API
- Solve quizzes
- Access other Canvas pages

### Tech Stack
- Manifest v3 (latest Chrome/Firefox standard)
- Vanilla JavaScript (no frameworks for MVP)
- Local storage for auth token
- HTTPS POST to backend

---

## 🔄 Data Flow Example

### User Gets AI Help
```
1. User visits canvas.kent.edu/courses/123/assignments/456
2. Extension detects assignment page
3. Shows "Get Help" button
4. User clicks button
5. Extension reads DOM:
   - Title: "Assignment 1: Intro to React"
   - Description: "Build a todo app..."
   - Context: extracts course materials
6. Extension calls:
   POST /api/assignment/complete
   {
     "auth_token": "ext_...",
     "course_id": 123,
     "assignment_id": 456,
     "assignment_title": "Assignment 1: Intro to React",
     "assignment_description": "Build a todo app...",
     "context": "[relevant course materials]"
   }
7. Backend receives request
8. Verifies auth_token
9. Calls Claude AI with all context
10. Stores draft in ai_completions
11. Returns draft to extension
12. Extension shows draft in popup
13. User copies draft
14. User manually fills Canvas form
15. User submits to Canvas
```

---

## 📅 Retention & Cleanup

### 7-Day Inactivity Policy
- Tracked via `last_accessed_at` on users table
- AI drafts NOT automatically deleted (user's work)
- User account deleted if no login for 7 days
- User can extend by logging in anytime

### Cleanup Job
- Runs daily (Rails cleanup job)
- Finds users with no login in 7+ days
- Deletes user account + all related data
- Deletes drafts only when deleting user

---

## 🎯 Next Steps

### To Proceed:
1. ✅ Review audit documents:
   - `AUDIT_BROWSER_EXTENSION.md`
   - `IMPLEMENTATION_PLAN.md`
   - `ARCHITECTURE_SUMMARY.md`
2. ✅ Approve auth flow (token-based? Yes)
3. ✅ Approve MVP scope (assignments only? Yes)
4. Start Phase 1 (database schema)

### Phase 1 Specifically:
```
1. Create migration SQL script
2. Test on staging database
3. Modify storage/database.py schema references
4. Run migration
5. Test users table still works
```

---

## 📌 Important Notes

### For Developers
- Extension auth token is different from Canvas API token
- No server-side Canvas API calls anymore
- All Canvas data comes from extension, not synced
- Database is now small (user accounts + drafts only)
- No more background sync jobs

### For Users
- One-time setup: copy token from settings to extension
- Then click "Get Help" on any assignment page
- Draft appears in extension popup
- Copy draft and manually submit to Canvas
- View history on web app dashboard

### For Architecture
- No passwords or credentials stored on server
- HTTPS only for extension ↔ backend
- Token-based auth is stateless
- Extension is optional (web app still works)
- Easy to extend with more features later

---

## 🐛 Bug Fixes

### PostgreSQL Timestamp Type Mismatch (Phase 5)

**Issue Found**: Local testing revealed type mismatch in extension_auth_tokens table
```
psycopg2.errors.DatatypeMismatch: column "created_at" is of type timestamp 
without time zone but expression is of type text
```

**Root Cause**: 
- New extension tables (`extension_auth_tokens`, `ai_completions`) use real PostgreSQL `TIMESTAMP` columns
- But insert/update statements were using `to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')`, which returns TEXT
- This incompatibility only appears with proper PostgreSQL, not SQLite (legacy)

**Affected Locations**:
- `storage/users.py:318` - `generate_extension_auth_token()` inserting into `created_at`
- `storage/users.py:347` - `verify_extension_auth_token()` updating `last_used_at`

**Fix Applied**:
- Changed `to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')` → `NOW()` 
- Uses native PostgreSQL TIMESTAMP type conversion
- Legacy `users` and `user_sessions` tables (TEXT timestamps) left unchanged
- `ai_completions` functions already correct (used `NOW()` directly)

**Verification**:
- ✅ Syntax check: All Python files compile cleanly
- ✅ Schema consistency: New tables use TIMESTAMP, legacy tables use TEXT
- ✅ No unintended changes to legacy code

---

## 🚀 Current Status

**Audit**: ✅ Complete  
**Architecture**: ✅ Designed  
**Documentation**: ✅ Ready  
**Implementation**: ⏸️ Awaiting approval  

**Ready to start Phase 1**: YES

---

## 📚 Reference Documents

- `AUDIT_BROWSER_EXTENSION.md` - Detailed component analysis
- `IMPLEMENTATION_PLAN.md` - Phase-by-phase breakdown with code
- `ARCHITECTURE_SUMMARY.md` - High-level overview and decisions
- This file - Implementation status and guidance

