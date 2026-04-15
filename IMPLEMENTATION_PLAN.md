# Browser Extension MVP - Implementation Plan

## Overview
This document outlines the specific implementation steps to transition from Canvas API token architecture to browser extension architecture.

---

## PHASE 1: Database Schema Refactor

### Objective
Transform database from "sync Canvas data" to "store user accounts + AI drafts"

### Changes

#### 1.1 Create New Tables
```sql
CREATE TABLE ai_completions (
    id SERIAL PRIMARY KEY,
    google_id TEXT NOT NULL,
    course_id INT,
    assignment_id INT,
    assignment_title VARCHAR(500) NOT NULL,
    assignment_description TEXT,
    context_summary TEXT,
    ai_draft TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (google_id) REFERENCES users(google_id) ON DELETE CASCADE
);
CREATE INDEX idx_ai_completions_user ON ai_completions(google_id);
CREATE INDEX idx_ai_completions_created ON ai_completions(created_at);

CREATE TABLE extension_auth_tokens (
    id SERIAL PRIMARY KEY,
    google_id TEXT NOT NULL UNIQUE,
    auth_token VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    FOREIGN KEY (google_id) REFERENCES users(google_id) ON DELETE CASCADE
);
```

#### 1.2 Modify users Table
```sql
ALTER TABLE users DROP COLUMN IF EXISTS canvas_api_token;
ALTER TABLE users DROP COLUMN IF EXISTS canvas_linked;
-- Keep: google_id, email, name, picture, is_admin, is_banned, 
--       last_accessed_at, created_at

-- If these don't exist yet, no change needed
```

#### 1.3 DROP Canvas Data Tables (when safe)
```
courses
assignments
submissions
files
pages
modules
module_items
```
**Note**: These are never used in new architecture. Can be dropped once migration is confirmed.

### Timeline
- Approx 1 hour to plan migration SQL
- Approx 30 min to test migration on staging

### Files to Modify
- `storage/database.py` - add new schema, remove old tables' references
- Migration script (new file)

---

## PHASE 2: Backend API Refactor

### Objective
Create new API endpoints for extension, remove old Canvas sync endpoints

### 2.1 New Endpoints to Create

#### `/api/auth/extension` (POST)
```python
Request:
{
  "user_id": "google_xxx",
  "action": "generate"  or "verify"
}

Response (generate):
{
  "auth_token": "ext_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}

Response (verify):
{
  "valid": true,
  "user_id": "google_xxx"
}

Purpose:
- generate: Create new auth token for extension (called from web app settings)
- verify: Extension verifies it can use this token (on first setup)
```

#### `/api/assignment/complete` (POST)
```python
Request:
{
  "auth_token": "ext_xxx",
  "course_id": 123,
  "assignment_id": 456,
  "assignment_title": "Assignment 1: Intro to X",
  "assignment_description": "Write about...",
  "context": "Course materials, notes, relevant readings..."
}

Response:
{
  "success": true,
  "draft_id": 789,
  "ai_draft": "Based on the materials provided...",
  "course_name": "CS 101"
}

Purpose: Generate AI draft from extension-provided context
```

#### `GET /api/completions` (GET)
```python
Query params: ?limit=20&offset=0

Response:
{
  "completions": [
    {
      "id": 789,
      "assignment_title": "...",
      "created_at": "2026-04-15T10:00:00Z",
      "preview": "Based on..."  // first 100 chars
    }
  ],
  "total": 45
}

Purpose: List saved AI drafts for dashboard
```

#### `GET /api/completions/{id}` (GET)
```python
Response:
{
  "id": 789,
  "assignment_title": "Assignment 1",
  "assignment_description": "...",
  "context_summary": "Materials provided included...",
  "ai_draft": "Full draft text...",
  "created_at": "2026-04-15T10:00:00Z"
}

Purpose: Get full draft details
```

#### `DELETE /api/completions/{id}` (DELETE)
```python
Response: {"success": true}

Purpose: Delete a saved draft
```

### 2.2 Routes to MODIFY

#### `/api/complete/<assignment_id>` (POST) - REFACTOR
**OLD**: Fetch from database, generate AI
**NEW**: Delete this endpoint (extension handles)
**REASON**: Extension provides context directly, no DB lookup needed

#### `/` (Dashboard) - MODIFY
**OLD**: Show Canvas courses from database
**NEW**: Show saved AI drafts, extension settings
**KEEP**: User info, navigation

### 2.3 Routes to REMOVE
- `/setup/canvas` (GET/POST) - no longer needed
- `/setup/canvas/reset` - no longer needed
- `/api/sync` (POST) - no sync needed
- `/api/sync_status` (GET) - no sync needed
- `/courses/*` - no database courses
- All Canvas course/assignment browsing

### Implementation Details

#### 2.3.1 Extension Auth Token Management
```python
# In storage/users.py - NEW FUNCTIONS

def generate_extension_auth_token(google_id: str) -> str:
    """Create or regenerate extension auth token for user."""
    import secrets
    token = secrets.token_hex(32)
    
    conn = get_users_conn()
    cur = _exec(conn, """
        INSERT INTO extension_auth_tokens (google_id, auth_token)
        VALUES (?, ?)
        ON CONFLICT(google_id) DO UPDATE SET
            auth_token = EXCLUDED.auth_token,
            created_at = NOW()
    """, (google_id, token))
    conn.commit()
    conn.close()
    return token

def verify_extension_auth_token(token: str) -> str or None:
    """Verify token and return google_id if valid."""
    conn = get_users_conn()
    cur = _exec(conn, """
        SELECT google_id FROM extension_auth_tokens
        WHERE auth_token = ?
    """, (token,))
    row = cur.fetchone()
    
    if row:
        # Update last_used_at
        _exec(conn, """
            UPDATE extension_auth_tokens 
            SET last_used_at = NOW()
            WHERE auth_token = ?
        """, (token,))
        conn.commit()
    
    conn.close()
    return row["google_id"] if row else None
```

#### 2.3.2 Assignment Completion Storage
```python
# In storage/database.py - NEW FUNCTIONS

def save_ai_completion(google_id: str, assignment_title: str, 
                      assignment_description: str, 
                      context_summary: str,
                      ai_draft: str,
                      course_id: int = None,
                      assignment_id: int = None) -> int:
    """Save AI-generated draft to database."""
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO ai_completions 
        (google_id, course_id, assignment_id, assignment_title,
         assignment_description, context_summary, ai_draft)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (google_id, course_id, assignment_id, assignment_title,
          assignment_description, context_summary, ai_draft))
    conn.commit()
    draft_id = cur.lastrowid
    conn.close()
    return draft_id

def get_user_completions(google_id: str, limit: int = 20, 
                        offset: int = 0) -> (list, int):
    """Get list of user's saved completions."""
    set_user_context(google_id)
    conn = get_conn()
    
    # Get total count
    total = conn.execute(
        "SELECT COUNT(*) as n FROM ai_completions WHERE google_id = ?",
        (google_id,)
    ).fetchone()["n"]
    
    # Get paginated results
    rows = conn.execute("""
        SELECT id, assignment_title, created_at,
               SUBSTR(ai_draft, 1, 100) as preview
        FROM ai_completions
        WHERE google_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (google_id, limit, offset)).fetchall()
    
    conn.close()
    return [dict(r) for r in rows], total

def get_completion(completion_id: int) -> dict or None:
    """Get full completion details."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM ai_completions WHERE id = ?",
        (completion_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_completion(completion_id: int, google_id: str) -> bool:
    """Delete a completion (verify ownership first)."""
    conn = get_conn()
    # Verify ownership
    owned = conn.execute(
        "SELECT id FROM ai_completions WHERE id = ? AND google_id = ?",
        (completion_id, google_id)
    ).fetchone()
    
    if owned:
        conn.execute("DELETE FROM ai_completions WHERE id = ?", 
                    (completion_id,))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False
```

#### 2.3.3 Refactored Assignment Agent
```python
# In agent/assignment_agent.py - MODIFY

def complete_assignment_from_context(
    assignment_title: str,
    assignment_description: str, 
    context_text: str,
    course_name: str = "Unknown Course",
    progress_cb=None
) -> str:
    """
    Generate assignment response from provided context.
    No database lookups - works from direct input.
    
    Args:
        assignment_title: Assignment name
        assignment_description: Instructions/prompt
        context_text: Relevant course materials (PDFs, notes, readings)
        course_name: Course name for system prompt
        progress_cb: Callback for progress updates
    
    Returns:
        AI-generated draft response
    """
    from config import ANTHROPIC_API_KEY
    
    if not ANTHROPIC_API_KEY:
        if progress_cb:
            progress_cb("Cần ANTHROPIC_API_KEY trong .env")
        return None
    
    def emit(msg):
        if progress_cb:
            progress_cb(msg)
    
    # Truncate context if too large
    if len(context_text) > MAX_TOTAL_CHARS:
        context_text = context_text[:MAX_TOTAL_CHARS]
    
    emit("Phân tích tài liệu...")
    
    # Build prompt
    system_prompt = (
        f"You are an excellent student at Kent State University taking {course_name}. "
        "Write thorough, well-organized, academically strong responses. "
        "Base your answer directly on the provided materials when available. "
        "Write in clear academic English."
    )
    
    user_prompt = f"""## Assignment: {assignment_title}

{assignment_description}

## Course Materials
{context_text}

## Your Response
Please write a complete, thoughtful response to this assignment:"""
    
    emit("Tạo câu trả lời...")
    
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        
        answer = response.content[0].text
        emit("Hoàn thành!")
        return answer
    
    except Exception as e:
        emit(f"Lỗi AI: {e}")
        return None
```

### Timeline
- Approx 2 hours to implement endpoints
- Approx 1 hour to test with mock extension

### Files to Modify
- `web/app.py` - add new endpoints, remove old ones
- `storage/users.py` - add extension auth functions
- `storage/database.py` - add completion storage functions
- `agent/assignment_agent.py` - refactor to accept context directly

---

## PHASE 3: Web App Refactor

### Objective
Update UI to show drafts instead of courses, add settings

### 3.1 New Pages

#### `/` - Dashboard (REFACTOR)
```html
Current: Shows Canvas courses from database
New: Shows:
- Extension status (connected? auth token set?)
- Recent AI drafts (list)
- Quick links (settings, logout)
- Help text for setup
```

#### `/settings` - Extension Settings (NEW)
```html
Shows:
- Extension auth token (with copy button)
- Instructions for pasting into extension
- Option to regenerate token
- Extension version check (if available)
```

#### `/drafts` - Draft History (NEW)
```html
Shows:
- List of all saved AI drafts
- Filter by date / assignment name
- View full draft
- Delete draft option
- Copy to clipboard
```

### 3.2 Routes to Remove
- `/courses/*`
- `/setup/canvas`
- `/api/sync*`

### 3.3 Template Changes
Update HTML templates to reflect new dashboard

### Timeline
- Approx 1.5 hours for templates
- Approx 1 hour for frontend logic

### Files to Modify
- `web/app.py` - update/remove routes
- `web/templates/dashboard.html` - new design
- `web/templates/settings.html` - new page
- `web/templates/drafts.html` - new page

---

## PHASE 4: Browser Extension MVP

### Objective
Create minimal extension to read assignment pages and call backend API

### 4.1 Extension Structure
```
manifest.json
popup.html
popup.js
content.js
background.js
styles.css
icons/
```

### 4.2 Key Functionality

#### Content Script (content.js)
```javascript
// Detects assignment page on canvas.kent.edu
// Reads DOM to extract:
// - Title
// - Description  
// - Files/links
// - Course name/ID

// Sends message to popup when ready
```

#### Popup (popup.html/js)
```
1. Check if auth token is set
2. Show loading spinner
3. Call backend /api/assignment/complete
4. Display AI draft
5. Provide copy button
6. Link to view in web app
```

#### Background Script (background.js)
```javascript
// Handle ext ↔ backend communication
// Store auth token securely (chrome.storage.sync)
// Validate token with backend on startup
```

### 4.3 Key Files

**manifest.json**
```json
{
  "manifest_version": 3,
  "name": "Canvas AI Assistant",
  "version": "0.1.0",
  "description": "AI-powered homework help for Canvas",
  "permissions": [
    "storage",
    "activeTab",
    "scripting",
    "webRequest"
  ],
  "host_permissions": [
    "*://*.kent.instructure.com/*"
  ],
  "action": {
    "default_popup": "popup.html",
    "default_title": "Canvas AI Assistant"
  },
  "background": {
    "service_worker": "background.js"
  }
}
```

### 4.4 Extension Setup Flow
1. User installs extension from Chrome Web Store (later) or local (now)
2. User clicks extension icon
3. Extension detects if auth token is set
4. If not set: shows link to web app ("/settings")
5. User copies token from web app settings
6. User pastes token into extension options
7. Extension validates token with backend
8. Extension shows "Ready"

### 4.5 Assignment Help Flow (MVP)
1. User on Canvas assignment page
2. User clicks extension icon
3. Extension reads assignment DOM:
   - Gets title
   - Gets description
   - Gets course name
   - Attempts to extract context (links, files)
4. Shows loading spinner
5. Sends to backend:
   ```javascript
   POST /api/assignment/complete
   {
     "auth_token": "...",
     "assignment_title": "...",
     "assignment_description": "...",
     "context": "..."  // from page or empty for MVP
   }
   ```
6. Shows draft in popup
7. User can:
   - Copy to clipboard
   - View full in web app
   - Try again (different context)

### Timeline
- Approx 4-6 hours for MVP extension
- Approx 1-2 hours for testing with backend

### Files to Create
- `extension/manifest.json`
- `extension/popup.html`
- `extension/popup.js`
- `extension/content.js`
- `extension/background.js`
- `extension/styles.css`

---

## PHASE 5: Integration & Testing

### 5.1 Manual Testing Checklist
- [ ] Extension installs and loads
- [ ] Auth token can be saved/regenerated
- [ ] Extension can read assignment page
- [ ] Backend receives assignment data
- [ ] AI generates draft
- [ ] Draft returns to extension
- [ ] Draft displays correctly
- [ ] User can copy draft
- [ ] Web app shows saved drafts
- [ ] Dashboard shows recent completions
- [ ] Settings page allows token regen

### 5.2 Security Testing
- [ ] Invalid tokens are rejected
- [ ] Users can't see other users' drafts
- [ ] Token rotation works
- [ ] CORS is properly configured

### 5.3 Edge Cases
- [ ] Large assignments with lots of context
- [ ] Assignments with no description
- [ ] Network timeout handling
- [ ] Rate limiting (if implemented)

### Timeline
- Approx 2 hours testing

---

## PHASE 6: Deployment

### 6.1 Pre-Deployment
- Update environment variables
- Run database migrations
- Seed data if needed
- Test in staging

### 6.2 Deployment Steps
1. Deploy backend to Railway
2. Update Chrome Web Store or host extension
3. Announce to beta testers
4. Monitor logs for errors

### Timeline
- Approx 1 hour deployment

---

## SUMMARY TIMELINE

| Phase | Tasks | Est. Hours | Status |
|-------|-------|-----------|--------|
| 1 | DB schema | 1.5 | Not Started |
| 2 | Backend API | 3 | Not Started |
| 3 | Web app UI | 2.5 | Not Started |
| 4 | Extension | 5 | Not Started |
| 5 | Testing | 2 | Not Started |
| 6 | Deploy | 1 | Not Started |
| **Total** | | **15** | |

**Realistic timeline for solo dev**: 2-3 days of focused work

---

## CODE ORGANIZATION

### Backend
```
canvas-app/
  ├── config.py (MODIFY)
  ├── web/
  │   ├── app.py (MAJOR REFACTOR)
  │   └── templates/
  │       ├── dashboard.html (REFACTOR)
  │       ├── settings.html (NEW)
  │       └── drafts.html (NEW)
  ├── storage/
  │   ├── users.py (MODIFY - add extension auth)
  │   └── database.py (MAJOR REFACTOR - remove Canvas tables, add completions)
  ├── agent/
  │   └── assignment_agent.py (REFACTOR - accept context directly)
  ├── tasks/
  │   └── cleanup.py (MINOR - remove Canvas tables)
  ├── sync/ (DELETE - entire folder)
  ├── auth/
  │   └── browser_auth.py (DELETE)
  └── api/
      └── canvas_client.py (MAYBE DELETE)
```

### Extension (New)
```
canvas-extension/
  ├── manifest.json
  ├── popup.html
  ├── popup.js
  ├── content.js
  ├── background.js
  ├── styles.css
  └── icons/
      ├── icon-16.png
      ├── icon-48.png
      ├── icon-128.png
```

---

## Success Criteria

✅ Extension can read assignment pages
✅ Extension can send data to backend
✅ Backend generates AI draft
✅ Draft displays in extension
✅ User can save draft history
✅ Web app shows all drafts
✅ Auth tokens work correctly
✅ 7-day cleanup removes old drafts
✅ No server-side Canvas API calls needed
✅ Ready for beta testing

