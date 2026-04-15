# Browser Extension Architecture - Summary & Key Decisions

## Status: Ready for Implementation

---

## THE PIVOT

### Why Leaving Token-Based Approach
1. **Unrealistic**: Users can't practically get Canvas API tokens
2. **Fragile**: Previous server-side login (Playwright) was unreliable
3. **Risky**: Server storing passwords or tokens is security/compliance liability
4. **No Path**: No way to scale this to many Canvas instances

### Why Browser Extension Is Right
1. **No Credentials**: Extension runs in user's existing Canvas session
2. **Secure**: No server-side password storage
3. **Reliable**: Uses real browser session, not automation
4. **Scalable**: Works for any Canvas instance without setup
5. **User Control**: User decides when to use it

---

## NEW ARCHITECTURE AT A GLANCE

```
┌─────────────────────────────────────────────────────────────┐
│ User's Browser                                               │
│                                                               │
│ [Canvas Page]          [Extension Button]                   │
│       ↓                       ↓                              │
│   Read DOM        →    Extract Assignment      →  Send Data │
│   (title, desc)         (title, desc, context)              │
│       │                                                     │
│       └─────────────────┬──────────────────────────┘        │
└────────────────────────┼─────────────────────────────────────┘
                         │ (HTTPS)
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Backend (Railway + Supabase)                                 │
│                                                               │
│  /api/assignment/complete ← Auth Check ← Extension Token    │
│       ↓                                                      │
│   Claude AI (Anthropic)                                     │
│       ↓                                                      │
│   Save Draft (ai_completions table)                         │
│       ↓                                                      │
│   Return Draft to Extension                                 │
└─────────────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ User                                                          │
│                                                               │
│ [Extension Shows Draft]  OR  [Web App Shows Draft]          │
│         ↓                             ↓                     │
│    Copy to Clipboard        View History / Settings         │
│         ↓                                                    │
│   User Pastes into Canvas & Submits Manually               │
└─────────────────────────────────────────────────────────────┘
```

---

## KEY COMPONENTS

### 1. Browser Extension (MVP)
**Purpose**: Read assignment context, send to backend, show draft

**When user clicks extension on assignment page**:
1. Extension reads assignment DOM
2. Extracts: title, description, any linked materials
3. Sends to backend with auth token
4. Shows loading spinner
5. Receives AI draft
6. Displays draft in popup with copy button

**What NOT in MVP**:
- Auto-filling Canvas form
- Quiz solving
- Multiple canvas instances
- Offline support

**Tech**: Manifest v3, Chrome/Firefox compatible

### 2. Backend API (New Endpoints)

**Authentication**:
```
POST /api/auth/extension
→ Generate random token (ext_xxx32chars...)
→ User pastes into extension settings
→ Extension includes in every request
```

**Main Endpoint**:
```
POST /api/assignment/complete
Input: {auth_token, assignment_title, assignment_description, context}
Output: {ai_draft, draft_id}
```

**History**:
```
GET /api/completions → list of user's drafts
GET /api/completions/{id} → full draft
DELETE /api/completions/{id} → delete draft
```

### 3. Web App (Simplified)

**Old Flow** (REMOVE):
- Canvas token setup
- Sync background job
- Course/assignment browsing
- Sync status monitoring

**New Flow** (KEEP/ADD):
- Google login
- Extension settings (show token)
- Draft history dashboard
- User settings

**MVP Pages**:
- `/` (dashboard - drafts list)
- `/drafts` (detailed history)
- `/settings` (extension setup)

---

## DATABASE SCHEMA CHANGES

### REMOVE These Tables
```sql
courses, assignments, files, pages, modules, 
module_items, submissions, user_sessions
```

**Why**: Extension provides all Canvas data; no need to store

### ADD These Tables
```sql
ai_completions
├── id (PK)
├── google_id (FK → users)
├── course_id (Canvas ID)
├── assignment_id (Canvas ID)
├── assignment_title
├── assignment_description
├── context_summary
├── ai_draft
├── created_at
└── updated_at

extension_auth_tokens
├── id (PK)
├── google_id (FK → users, UNIQUE)
├── auth_token (UNIQUE, 64-char)
├── created_at
└── last_used_at
```

### MODIFY users Table
```
REMOVE: canvas_api_token, canvas_linked
KEEP: google_id, email, name, picture, is_admin, is_banned,
      last_accessed_at, created_at, sync_status (can remove)
```

---

## AUTHENTICATION FLOW (Critical!)

### How does extension prove "I'm the user's extension"?

**Option A: Token-Based (RECOMMENDED FOR MVP)**
1. User logs into web app via Google
2. Web app generates random `extension_auth_token` (32 chars)
3. Web app shows token in `/settings` page
4. User copies token from settings
5. User opens extension popup → "Enter Auth Token"
6. User pastes token into extension
7. Extension stores locally, validates with backend
8. Extension includes token in every API request
9. Backend verifies token matches user

**Pros**:
- Simple to implement
- No canvas session detection needed
- User explicitly approves extension

**Cons**:
- Requires user action (copy/paste)
- Token can be shared/leaked

**Option B: Canvas Session Detection (Possible Future)**
- Extension detects user is logged into Canvas
- Extension sends Canvas identity to backend
- Backend verifies user is authenticated on web app
- More automatic but more complex

**DECISION**: Use Option A for MVP (simpler, proven pattern)

---

## DATA FLOW EXAMPLES

### Example 1: User Gets AI Help on Assignment
```
1. User on Canvas: canvas.kent.edu/courses/123/assignments/456
2. User clicks extension icon
3. Extension content.js reads DOM:
   - Title: "Assignment 1: Intro to React"
   - Description: "Build a simple todo app..."
   - Context: extracted from course materials if available
4. Extension sends:
   POST /api/assignment/complete
   {
     "auth_token": "ext_xxx",
     "course_id": 123,
     "assignment_id": 456,
     "assignment_title": "Assignment 1: Intro to React",
     "assignment_description": "Build a simple...",
     "context": "From course materials..."
   }
5. Backend:
   - Verifies auth_token
   - Calls Claude API with context
   - Gets draft response
   - Saves to ai_completions table
   - Returns draft
6. Extension popup shows draft
7. User copies draft and manually submits to Canvas
```

### Example 2: User Views Draft History
```
1. User goes to web app → clicks "My Drafts"
2. Web app calls GET /api/completions
3. Backend returns list of user's AI drafts
4. User sees recent assignments and can click to view full draft
5. User can copy, delete, or review old attempts
```

### Example 3: 7-Day Cleanup
```
1. Nightly cleanup job runs
2. Finds drafts where last_accessed_at > 7 days ago
3. Deletes those draft records (not assignments, just drafts)
4. User's Google account still active if they've logged in
5. User data deleted only if user hasn't accessed anything in 7 days
```

---

## WHAT GETS REUSED FROM CURRENT CODE

### ✅ KEEP (70-100% reusable)
- `config.py` - environment variables
- `storage/users.py` - user auth, CRUD (with Canvas token stuff removed)
- `agent/assignment_agent.py` - core AI logic (refactored to accept context)
- `storage/database.py` - connection pooling, context management (tables refactored)
- `tasks/cleanup.py` - retention job (table names updated)
- `web/app.py` - Google OAuth parts (sync/Canvas parts removed)

### ⚠️ PARTIALLY REUSABLE (20-50%)
- Web templates - need redesign for new flow

### ❌ DELETE (Not reusable)
- `sync/*` - entire folder (no server-side sync)
- `auth/browser_auth.py` - Playwright login
- `api/canvas_client.py` - no Canvas API calls from backend

---

## MVP USER EXPERIENCE

### Setup (One-Time)
1. User visits canvas-app.herokuapp.com
2. "Sign in with Google"
3. Gets redirected to settings page
4. Sees extension auth token (auto-generated)
5. Instructions: "Copy this token, go to extension settings, paste it"
6. User installs extension from Chrome Web Store (or local)
7. User opens extension, goes to settings
8. User pastes token
9. Extension says "Connected! Ready to help."

### Using AI Help
1. User opens assignment on Canvas
2. Extension button visible on page
3. User clicks button
4. Extension reads assignment
5. Extension sends to backend
6. Loading spinner (2-5 seconds)
7. Draft appears in popup
8. User copies draft
9. User fills in Canvas form manually
10. User submits assignment as usual

### Viewing History
1. User visits canvas-app.herokuapp.com
2. Sees dashboard with recent AI drafts
3. Can click "View All" to see history
4. Can search by assignment name
5. Can view full draft or delete it

---

## SECURITY & PRIVACY CONSIDERATIONS

### What Data Is Stored?
- User account (Google ID, name, email)
- Extension auth token (random string)
- AI drafts (assignment context + AI response)
- **NOT**: Canvas credentials, API tokens, passwords

### What Data Is NOT Stored?
- Canvas login credentials
- Canvas API tokens
- User's actual Canvas submissions
- Browser history
- Any personally identifiable data beyond Google profile

### Auth Token Security
- 32 random bytes (256-bit entropy)
- Stored in Supabase (encrypted at rest)
- User can regenerate anytime
- Invalid if not used for > 30 days (maybe?)

### Extension Security
- Manifest v3 (latest standard)
- No access to other sites (only *.kent.instructure.com)
- Communication over HTTPS only
- Token stored in chrome.storage.sync (encrypted by browser)

---

## IMPLEMENTATION READINESS

### Audit Status: ✅ COMPLETE
- [x] Analyzed all 22 Python modules
- [x] Identified reusable components
- [x] Proposed new schema
- [x] Designed auth flow
- [x] Spec'd endpoints

### Architecture Status: ✅ APPROVED
- [x] Data flow documented
- [x] Security reviewed
- [x] MVP scope defined
- [x] Technology choices made

### Ready to Start: YES
- Phase 1: DB schema (1.5 hrs)
- Phase 2: Backend API (3 hrs)
- Phase 3: Web app UI (2.5 hrs)
- Phase 4: Extension (5 hrs)
- Phase 5: Testing (2 hrs)
- **Total: ~14 hours** of focused dev work

---

## ANSWERS TO KEY QUESTIONS

### Q: How does extension know which user?
**A**: Extension stores auth token (copy/paste from web app). Token maps to Google ID in database.

### Q: What if user loses their token?
**A**: User logs into web app, generates new token in settings.

### Q: Can one token be used by multiple people?
**A**: Yes, but it maps to whoever created it. Tokens can be share-able (not a problem for initial MVP).

### Q: What if user uninstalls extension?
**A**: Old drafts still in database. User can reinstall and use same token, or generate new token.

### Q: How much data is sent to backend?
**A**: Assignment title (~100 bytes) + description (~500 bytes) + context (~5KB). Total ~6KB per request.

### Q: Is this secure?
**A**: Yes. No passwords stored, no Canvas credentials on server, all over HTTPS, user-controlled token.

### Q: Can we auto-fill Canvas form later?
**A**: Yes. In v1.1, extension can use DOM manipulation to pre-fill the submission form.

### Q: Can we add quiz support?
**A**: Yes, but requires extension to interact with quiz page (more complex). v1.1+.

### Q: Can we support other Canvas instances?
**A**: MVP is Kent State only. v1.1 can add instance detection.

---

## NEXT STEPS

1. ✅ **Read & Approve** this architecture
2. **Confirm auth flow** (token-based? canvas-session-based?)
3. **Confirm MVP scope** (just assignments? include anything else?)
4. **Start Phase 1** (database schema)
5. Update CLAUDE.md with new architecture
6. Implement phases sequentially

---

## DOCUMENT REFERENCES
- `AUDIT_BROWSER_EXTENSION.md` - Detailed audit of all components
- `IMPLEMENTATION_PLAN.md` - Step-by-step phase breakdown with code examples
- This file - High-level summary and key decisions

