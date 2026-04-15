# CANVAS App - Browser Extension Architecture

## Status: Architecture Audit Complete - Ready for Implementation

**Updated**: 2026-04-15

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

### Phase 1: Database Schema (1.5 hours)
- Remove Canvas data tables (courses, assignments, files, etc.)
- Add `ai_completions` table (store AI-generated drafts)
- Add `extension_auth_tokens` table (auth management)
- Remove `canvas_api_token` column from users table

### Phase 2: Backend API (3 hours)
- Implement `/api/auth/extension` (generate/verify tokens)
- Implement `/api/assignment/complete` (receive context, return draft)
- Implement `/api/completions` (list saved drafts)
- Refactor `assignment_agent.py` to accept context directly

### Phase 3: Web App UI (2.5 hours)
- Remove Canvas token setup page
- Remove course/assignment browsing
- Add `/settings` page (show extension token)
- Add `/drafts` page (draft history)
- Modify `/` dashboard (show recent drafts)

### Phase 4: Browser Extension (5 hours)
- Create Manifest v3 extension
- Build popup UI (show draft)
- Create content script (read assignment page)
- Implement auth token management
- Add API communication

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

