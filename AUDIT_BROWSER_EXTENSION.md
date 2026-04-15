# Browser Extension Migration - Comprehensive Audit & Architecture

## Date: 2026-04-15
## Status: Audit Complete, Ready for Implementation

---

## PART 1: CURRENT CODEBASE AUDIT

### Current Architecture (Being Deprecated)
```
User → Google Login → Canvas API Token Setup → Background Sync
                          ↓
                   Store Canvas Data in DB
                          ↓
                   Web App shows courses/assignments
                          ↓
                   AI helps with assignments
```

**Why This Doesn't Work**:
- Users can't realistically get Canvas API tokens
- No way to obtain tokens from real users at scale
- Previous server-side Playwright login was fragile and risky
- Current architecture assumes data already in database (requires token)

---

## Component-by-Component Analysis

### ✅ REUSABLE Components

#### 1. **config.py** (60 lines)
- **Current use**: Environment variables, paths, base configuration
- **Reusable**: ✅ YES (100%)
- **Changes**: Remove Canvas-specific config, add extension config
- **Keep**: Database URL, Flask secret, API keys, paths
- **Add**: Extension API key, allowed extension origins
- **Code**:
```python
# KEEP:
FLASK_SECRET_KEY
ANTHROPIC_API_KEY
DATABASE_URL
DOWNLOADS_DIR
BASE_DIR

# ADD:
EXTENSION_AUTH_SECRET  # for extension authentication
ALLOWED_EXTENSION_ORIGINS  # for CORS with extension
```

#### 2. **storage/users.py** (301 lines)
- **Current use**: User auth, Canvas credentials (no longer needed)
- **Reusable**: ✅ PARTIAL (70%)
- **Keep**: Google user auth, user CRUD, session management
- **Remove**: `set_canvas_api_token`, `get_canvas_api_token`, Canvas token encryption
- **Modify**:
  - Remove `canvas_api_token` column (no longer storing tokens)
  - Keep `last_accessed_at`, `created_at` for retention
  - Keep `is_admin`, `is_banned` for user management
- **New functions needed**:
  - `get_extension_auth_token(google_id)` - for extension auth
  - `verify_extension_auth(token)` - validate extension requests

#### 3. **agent/assignment_agent.py** (384 lines)
- **Current use**: AI completion with database context
- **Reusable**: ✅ PARTIAL (60%)
- **Keep**: Core AI logic, gathering module context, HTML stripping
- **Refactor**:
  - `complete_assignment()` currently fetches from DB - needs to accept context as param
  - `gather_module_context()` currently queries database - needs to work from extension-provided data
  - Move PDF reading logic to optional (extension provides raw content)
- **Usage in new arch**: Backend receives assignment title/description/context from extension, passes to refactored version
- **Example refactoring**:
```python
# OLD:
def complete_assignment(assignment_id: int, progress_cb=None):
    assignment = get_assignment(assignment_id)  # DB lookup
    ctx = gather_module_context(assignment_id)  # Sync query

# NEW:
def complete_assignment_from_context(
    assignment_title: str,
    assignment_description: str,
    context_text: str,
    course_name: str = "Unknown Course",
    progress_cb=None
):
    # No DB lookups, just AI from provided context
```

#### 4. **storage/database.py** (493 lines)
- **Current use**: Canvas data schema and sync operations
- **Reusable**: ✅ PARTIAL (40%)
- **Keep**:
  - Database connection handling
  - User context management (`set_user_context`, `clear_user_context`)
  - Core helper functions (execute, init_db)
- **Remove**: All Canvas data tables (courses, assignments, files, modules, pages, submissions)
- **Keep**: User isolation logic (google_id composite keys)
- **New tables needed**:
  - `ai_completions` - store drafts (user_id, assignment_title, assignment_description, ai_draft, created_at)
  - Maybe `completion_history` if needed
- **Rationale**: Extension provides all Canvas data; web app only stores user-generated content

#### 5. **tasks/cleanup.py** (186 lines)
- **Current use**: Auto-delete inactive user data
- **Reusable**: ✅ YES (90%)
- **Modify**:
  - Remove deletion of Canvas data tables (don't exist anymore)
  - Keep user deletion logic
  - Keep timestamp-based retention (7 days `last_accessed_at`)
- **Change**: Instead of deleting courses/assignments/files, only delete user records and related AI drafts

### ❌ NOT REUSABLE (Deprecated)

#### 1. **web/app.py** (754 lines) - 40% reusable
- **Sections to REMOVE**:
  - Routes: `/setup/canvas`, `/setup/canvas/reset`, `/api/sync`, `/api/sync_status`
  - Routes: `/courses/*`, `/api/quiz/*` (unless repurposing)
  - Background sync function `_trigger_sync()`
  - All database queries for Canvas data
  - Entire Playwright/browser automation setup (was for login, now not needed)

- **Sections to KEEP**:
  - Google OAuth flow (keep `/login`, `/auth/google`, `/auth/google/callback`, `/logout`)
  - Health check route
  - User session/context management
  - `_setup_user_context()` helper

- **Routes to MODIFY**:
  - `/api/complete/<assignment_id>` → Accept extension data, not database lookups

- **Routes to ADD**:
  - `/api/auth/extension` - POST to get extension auth token
  - `/api/assignment/complete` - POST from extension with context, return AI draft
  - `/dashboard` - Show saved drafts, user settings
  - `/drafts` - View/manage AI draft history

#### 2. **sync/* files** (assignments, courses, files, modules, pages, organizer)
- **Status**: ❌ DELETE
- **Reason**: Extension provides Canvas data, no more server-side sync
- **Impact**: Remove ~500 lines of dead code

#### 3. **auth/browser_auth.py** (390 lines)
- **Status**: ❌ DELETE
- **Reason**: Playwright login no longer needed, extension handles Canvas auth

#### 4. **api/canvas_client.py** (81 lines)
- **Status**: ⚠️ MAYBE KEEP (low probability)
- **Reason**: Won't call Canvas API from backend (extension does)
- **Unless**: Backend needs to fetch assignment data from Canvas API as fallback - probably not needed

---

## PART 2: NEW ARCHITECTURE DESIGN

### Overall Flow
```
Extension (running in Canvas browser)
  1. User opens assignment page on Canvas
  2. Extension reads page DOM to extract:
     - Assignment title
     - Description
     - Any attached files/links
     - Module/course context
  3. Extension sends to backend:
     POST /api/assignment/complete
     {
       "auth_token": "ext_xxx",
       "user_id": "google_xxx",
       "course_id": 123,
       "assignment_id": 456,
       "assignment_title": "...",
       "assignment_description": "...",
       "context": "..."  // relevant course materials
     }

Backend
  1. Verify extension auth token
  2. Extract assignment data
  3. Call Claude AI with context
  4. Save draft to `ai_completions` table
  5. Return draft to frontend

Extension/Web App
  1. Show draft to user
  2. User can copy, edit, submit manually to Canvas
  3. User can view draft history on web app dashboard
```

### Data Flow Diagram
```
Canvas Page (Real User Session)
    ↓ (Extension reads DOM/context)
Browser Extension
    ↓ (Sends assignment + context)
Backend API (/api/assignment/complete)
    ↓ (Validate auth, extract context)
Claude AI API
    ↓ (Generate draft)
Backend Database (ai_completions table)
    ↓ (Save draft)
Extension OR Web App UI (show draft)
    ↓ (User copies/submits manually)
Canvas (User submits directly)
```

### Authentication Flow (Extension ↔ Backend)

**Current Problem**: How does extension prove "I'm extension for user X"?

**Solution: Extension-Specific Auth Token**

1. User logs into web app via Google
2. Web app generates `extension_auth_token` (random 32-char string)
3. Web app shows token in settings (or API returns it)
4. User pastes token into extension settings
5. Extension stores token locally
6. Extension includes token in every request to backend
7. Backend verifies token matches a user, returns user_id

**Alternative (Better for UX)**:
- Extension detects user's Canvas session (reads Canvas session cookie)
- Extension sends "I see user X is logged into Canvas at Kent State"
- Backend has a mapping of Canvas sessions to user accounts
- Backend trusts extension because user authenticated it already

**Implementation**: 
```javascript
// Extension sends:
{
  "auth_token": "...",        // Extension-specific token (shared secret)
  "user_id": "google_xxx",    // From web app settings
  "request_signature": "..."  // HMAC of request body with auth_token
}

// Backend verifies:
1. auth_token exists in user's settings
2. Signature matches (prevents token replay/modification)
3. Request is fresh (timestamp in signature)
```

### Database Schema Changes

**REMOVE Tables**:
- courses
- assignments
- submissions
- files
- pages
- modules
- module_items

**KEEP Tables**:
- users (minus canvas_api_token column)
- user_sessions (or rename to extension_auth)

**ADD Tables**:
```sql
CREATE TABLE ai_completions (
  id SERIAL PRIMARY KEY,
  google_id TEXT NOT NULL,
  course_id INT,                    -- Canvas course ID
  assignment_id INT,                 -- Canvas assignment ID
  assignment_title VARCHAR(500),
  assignment_description TEXT,
  context_summary TEXT,              -- First 500 chars of context sent
  ai_draft TEXT,                     -- The AI-generated draft
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  FOREIGN KEY (google_id) REFERENCES users(google_id)
);

CREATE TABLE extension_auth_tokens (
  id SERIAL PRIMARY KEY,
  google_id TEXT NOT NULL UNIQUE,
  auth_token VARCHAR(64) NOT NULL,   -- Random token
  created_at TIMESTAMP,
  last_used_at TIMESTAMP,
  FOREIGN KEY (google_id) REFERENCES users(google_id)
);
```

---

## PART 3: MVP SCOPE DEFINITION

### MVP Goals
✅ Assignment help (title + description + context → draft)
❌ Quiz automation (save for v1.1)
❌ Auto-submit (save for v1.1)
❌ Multiple Canvas instances (focus on Kent State)
❌ Subscription/billing (save for v1.1)
❌ Offline support (not needed)

### MVP User Journey
1. User goes to canvas.kent.edu
2. User is already logged into Canvas (existing session)
3. User opens an assignment
4. Extension button appears on assignment page
5. User clicks "Get AI Help"
6. Extension reads assignment page:
   - Title
   - Description
   - Any files/links
   - Course context
7. Extension shows loading spinner
8. Backend:
   - Gets context from extension data
   - Calls Claude AI
   - Saves draft
9. Extension shows draft to user
10. User can:
    - Copy draft
    - View in web app
    - See history
    - Try again with different prompts

### Extension Capabilities (MVP)
- Read assignment page DOM
- Read Canvas session (no API token needed)
- Send assignment data to backend
- Receive draft response
- Display draft in popup or sidebar
- Link to web app for history

### Web App (MVP)
- Google login
- Extension settings (show/set auth token)
- Dashboard with saved drafts
- Draft history (list/search/view)
- Copy to clipboard
- Logout

### Backend APIs (MVP)
```
POST /api/auth/extension
  Input: google_id, extension_auth_token
  Output: auth_status
  Purpose: Verify extension can access this user's account

POST /api/assignment/complete
  Input: auth_token, assignment_title, assignment_description, context
  Output: ai_draft
  Purpose: Get AI-generated draft
  Auth: Extension token from header or body

GET /api/completions
  Output: List of saved drafts
  Purpose: Show history on web app

DELETE /api/completions/{id}
  Purpose: Delete a draft
```

---

## PART 4: MIGRATION PATH

### What Gets REMOVED from Web App
- Canvas token setup UI
- Sync status monitoring
- Course/assignment browsing (data from database)
- All database queries for Canvas data
- Sync background jobs

### What Gets MODIFIED
- Dashboard (show drafts instead of courses)
- API endpoints (accept extension data instead of DB lookups)
- AI logic (work from extension-provided context)
- Auth (add extension token validation)

### What Gets ADDED
- Extension auth management (generate tokens)
- API endpoints for extension
- Draft history storage and display
- Settings page (show extension token)

### Phased Implementation
**Phase 0**: Code cleanup & planning (current)
**Phase 1**: Database schema refactor (remove Canvas tables, add completion table)
**Phase 2**: Backend API refactor (remove sync, add extension endpoints)
**Phase 3**: Web app refactor (remove Canvas UI, add settings/drafts)
**Phase 4**: Browser extension MVP (basic assignment reading + API calls)
**Phase 5**: Integration & testing
**Phase 6**: Deployment

---

## PART 5: RECOMMENDED NEXT STEPS

1. **Review this audit** - agree/disagree with reusability assessments
2. **Finalize Extension Auth Design** - decide between token-based or Canvas-session-based
3. **Create Extension Boilerplate** - start simple (Manifest v3, popup)
4. **Begin Phase 1** - refactor database schema
5. **Implement New APIs** - `/api/assignment/complete`, `/api/auth/extension`
6. **Test Extension ↔ Backend** - manual testing with Chrome DevTools
7. **Polish Web App** - dashboard for drafts, settings

---

## KEY DECISIONS TO CONFIRM

### Q1: How should extension authenticate?
- Option A: User copies auth token from web app settings to extension settings
- Option B: Extension uses Canvas session detection + web app already authenticated
- **Recommendation**: Option A (simpler, more explicit, no Canvas session detection needed)

### Q2: What data should extension send?
- Option A: Raw HTML of page + let backend parse
- Option B: Extension parses, sends clean JSON (title, description, files)
- **Recommendation**: Option B (less data, cleaner API, extension does work)

### Q3: Should we keep any Canvas data in database?
- Option A: NO - only store user account + AI drafts
- Option B: YES - cache some data for faster lookups
- **Recommendation**: Option A (simpler, no stale data issues)

### Q4: What about course materials (PDFs, notes)?
- Option A: Extension sends course materials for context
- Option B: Backend requests from Canvas API (requires auth)
- Option C: User manually provides context (bad UX)
- **Recommendation**: Option A if extension can access, Option B as fallback

### Q5: How long to keep AI drafts?
- Option A: 7 days (same as before)
- Option B: 30 days (good for revision history)
- Option C: Forever (could get expensive)
- **Recommendation**: 30 days for MVP (user can review old attempts)

