# COMPREHENSIVE AUDIT REPORT
## Canvas App - Current State Assessment
**Date**: 2026-04-15
**Auditor Role**: Principal Engineer + Product Architect

---

## 🎯 EXECUTIVE SUMMARY

**Current Status**: ~75% complete, with critical issues blocking production deployment

**Overall Grade**: C+ (Works but has loose ends)

The app has been successfully migrated from server-side password login to Canvas API token authentication. However, there are **8 identified issues** preventing it from being production-ready. Most are easily fixable but require attention before public deployment.

---

## ✅ WHAT'S WORKING WELL

### 1. **Google OAuth Authentication** ✓
- `web/app.py`: Proper OAuth flow with authlib
- Session-based auth (not per-request DB calls)
- User isolation via thread-local google_id
- Status: **SOLID**

### 2. **Database Architecture** ✓
- PostgreSQL with Supabase-compatible schema
- Per-user data isolation via (google_id, id) composite keys
- Timestamp tracking (synced_at) for retention
- User context management is thread-safe
- Status: **SOLID**

### 3. **Canvas API Token Authentication** ✓
- Setup form correctly asks for Canvas API token
- Token is validated against Canvas API before saving
- Token is encrypted with Fernet (key from FLASK_SECRET_KEY)
- Stored in `users.canvas_api_token` column
- Status: **WORKING**

### 4. **Data Sync Pipeline** ✓
- `_trigger_sync()` properly uses Canvas API token
- Syncs courses, assignments, files, modules, pages
- Background thread with progress updates
- No Playwright login in main flow
- Sets synced_at timestamps on all upserted data
- Status: **WORKING**

### 5. **Data Retention & Cleanup** ✓
- `tasks/cleanup.py` implemented with proper logic
- Deletes inactive users after configurable days (default 7)
- Removes local files and database records
- Flask CLI command available: `flask cleanup`
- Admin UI at `/admin/cleanup` for manual triggers
- Status: **WORKING**

### 6. **AI Features** ✓ (Partially)
- Assignment agent: Uses OpenAI API, reads PDFs for context, streams responses
- Quiz agent: Uses GPT-4o Vision, accepts both api_token and cookies
- Both work with Canvas API token integration
- Status: **WORKING** (see issues below)

---

## 🔴 CRITICAL ISSUES (Must Fix)

### Issue #1: Admin Dashboard References Deleted Column
**Severity**: MEDIUM (UI error, not data loss)
**Location**: `web/templates/admin/dashboard.html:92`, `web/templates/admin/user_detail.html:72`
**Problem**: Templates display `{{ u.canvas_user }}` which no longer exists in DB schema
**Impact**: Confusing UI, displays blank or errors
**Fix**: Remove canvas_user from admin templates (it's not sensitive data anyway, just remove it)
**Time to fix**: 5 minutes

### Issue #2: user_sessions Table Still Has Legacy Columns
**Severity**: LOW (compatibility, not breaking)
**Location**: `storage/users.py`, `user_sessions` table
**Problem**: Table stores `cookies_json` and `api_token` from old flow (Playwright logins)
**Impact**: 
- Takes up space storing cookies that are no longer created
- `load_user_session()` still used in submission/quiz endpoints
- Creates confusion about data flow
**Fix**: Phase out gradually:
- Keep table for now (backward compatibility)
- Stop creating new cookies (already done)
- Update endpoints to only use api_token from `users.canvas_api_token`
**Time to fix**: 30 minutes

### Issue #3: Assignment Agent Uses Wrong AI API
**Severity**: MEDIUM (feature works but with wrong provider)
**Location**: `agent/assignment_agent.py:16, 235, 340-341`
**Problem**: 
- Doc comment says "GPT-4o" but should be Claude (Anthropic)
- Code uses `OPENAI_API_KEY` and imports `OpenAI`
- Should use Anthropic Claude instead
**Impact**: Uses wrong AI provider for assignment help
**Fix**: 
1. Add `ANTHROPIC_API_KEY` to config.py
2. Switch assignment_agent to use Anthropic Claude API
3. Update docstring
**Time to fix**: 45 minutes

### Issue #4: Missing ANTHROPIC_API_KEY in Config
**Severity**: MEDIUM (feature can't work without it)
**Location**: `config.py`
**Problem**: No ANTHROPIC_API_KEY environment variable defined
**Impact**: Assignment agent can't run without OPENAI_API_KEY (wrong provider anyway)
**Fix**: Add ANTHROPIC_API_KEY to config.py
**Time to fix**: 5 minutes

### Issue #5: browser_auth.py Still Exists But Is Dead Code
**Severity**: LOW (maintenance debt, not functional issue)
**Location**: `auth/browser_auth.py` (entire file)
**Problem**: 
- 390 lines of Playwright login code
- Not imported anywhere in the main flow
- Confuses future developers
- Should be deprecated
**Impact**: 
- Code confusion
- Dependency on Playwright even though not needed for main flow
- Future browser extension migration won't use this
**Fix**: Either:
- Option A: Delete it now (quiz agent doesn't need it)
- Option B: Mark as deprecated with clear warning
- I recommend: Keep for reference for now, but clearly mark as DEPRECATED
**Time to fix**: 5 minutes (just add comment)

### Issue #6: Submission Endpoint Tries to Load Legacy Cookies
**Severity**: MEDIUM (works but inefficient and confusing)
**Location**: `web/app.py` submit endpoint, line ~640
**Problem**: 
```python
cookies, api_token = load_user_session(session["google_id"])
if not cookies and not api_token:
    return error
```
- Loads cookies that won't exist in new flow
- Should only use api_token
- Creates false impression that cookies matter
**Impact**: Works but misleading
**Fix**: Update to only use api_token from users table, not user_sessions
**Time to fix**: 15 minutes

### Issue #7: Quiz Agent Still Expects Cookies as Fallback
**Severity**: LOW (works but confusing)
**Location**: `web/app.py` quiz endpoint, `agent/quiz_agent.py`
**Problem**:
```python
cookies, api_token = load_user_session(...)
if not api_token and not cookies:  # Wrong priority
```
- Should check api_token from users table directly
- Cookies from old sessions won't exist
- Confusing fallback logic
**Impact**: Works with api_token, but cookies won't be there for fallback
**Fix**: Clean up to only use api_token from users.canvas_api_token
**Time to fix**: 20 minutes

### Issue #8: Incomplete Documentation in Code
**Severity**: LOW (developer confusion)
**Problem**:
- Comments still reference old password-based flow in some places
- CLAUDE.md doesn't reflect all the issues found here
- Some docstrings are outdated
**Impact**: Developers are confused about the actual implementation
**Fix**: Update docstrings and comments
**Time to fix**: 30 minutes

---

## ✋ BLOCKING ISSUES FOR PRODUCTION

### Must Fix Before Public Deployment:
1. ✅ Admin template error (Issue #1)
2. ✅ ANTHROPIC_API_KEY missing (Issue #4)  
3. ✅ Assignment agent using wrong API (Issue #3)
4. ✅ Submission endpoint confusion (Issue #6)
5. ⚠️ browser_auth.py deprecation (Issue #5) - optional but recommended

### Can Fix Post-Launch:
- Issue #2: user_sessions cleanup (can keep as-is for compatibility)
- Issue #7: quiz endpoint cleanup (already works, just could be cleaner)
- Issue #8: documentation (doesn't block functionality)

**Total time to fix blockers**: ~1.5 hours

---

## 📋 DETAILED ARCHITECTURAL ASSESSMENT

### Current Architecture Status

**Phase 1: Canvas Token Auth** ✓ 85% COMPLETE
- ✓ Token setup form
- ✓ Token encryption & storage
- ✓ Token validation on setup
- ✓ Sync flow uses tokens
- ⚠️ Admin UI shows deleted field (template bug)
- ⚠️ Submission endpoint loads legacy cookies

**Phase 2: Data Retention** ✓ 95% COMPLETE
- ✓ Cleanup logic implemented
- ✓ Admin UI working
- ✓ Timestamps tracked correctly
- ✓ 7-day retention policy configured
- ⚠️ Minor: user_sessions still storing cookies (not harmful)

**Phase 3: Production Hardening** ✓ 60% COMPLETE
- ✓ Dockerfile configured
- ✓ Railway-ready
- ✓ Health check endpoint
- ✓ Error handling in place
- ⚠️ AI provider mismatch (using OpenAI for assignment when should use Claude)
- ⚠️ Dead code not cleaned up (browser_auth.py)
- ⚠️ Some admin UI issues

---

## 🏗️ RECOMMENDED TARGET ARCHITECTURE

### Short Term (Before Public Launch)
**Goal**: Fix all issues, deploy to Railway, support 10-100 students

**Approach**: Keep current architecture with fixes
- Web app only (no extension yet)
- User provides Canvas API token
- Data synced server-side
- AI responses generated and shown in-app
- File storage: local for now (expires in 7 days)

### Medium Term (Weeks 2-4)
**Goal**: Prepare for browser extension migration

**Preparation Work**:
1. Clean up legacy code (browser_auth.py)
2. Decouple Canvas sync from web app (make sync service reusable)
3. Design extension-compatible authentication
4. Plan user session lifecycle for extension

### Long Term (Months 2+)
**Goal**: Migrate to web app + browser extension

**Architecture**:
```
Extension (user's computer)
  ↓ (reads Canvas session from browser)
  ↓ (sends extracted data securely)
  ↓
Web App Backend (Railway + Supabase)
  ↓ (processes AI requests)
  ↓ (stores history, billing, etc.)
  ↓ 
User Browser (shows results)
```

---

## 🚨 SECURITY & COMPLIANCE CHECK

### Current Security Status
- ✓ No passwords stored on server
- ✓ API tokens encrypted with Fernet
- ✓ Per-user data isolation
- ✓ SQL injection protection (parameterized queries)
- ✓ CSRF protection (Flask sessions)
- ✓ Google OAuth proper scoping
- ⚠️ Browser_auth.py still ships code that could be misused
- ⚠️ Old cookies tables could be security concern long-term

### Compliance Status (FERPA)
- ✓ Can delete user data (7-day retention)
- ✓ User controls Canvas access (revocable token)
- ✓ No password storage
- ✓ Per-student isolation
- ⚠️ Needs audit logging (future improvement)
- ⚠️ No data export feature yet

---

## 📊 CODE QUALITY ASSESSMENT

### Strengths
- Good separation of concerns (sync, agents, storage, web)
- Thread-safe user context management
- Proper error handling with progress messages
- Efficient database queries with proper indexing
- Clean Flask structure with blueprints

### Weaknesses
- Dead code (browser_auth.py) should be removed
- Legacy columns in database
- Inconsistent error messages (some Vietnamese, some English)
- Some code duplication (session loading)
- Documentation lag (code moved ahead of CLAUDE.md)

### Debt
- browser_auth.py should be removed
- user_sessions table schema could be simplified
- Test coverage: None (not tested)
- Type hints: Missing in most functions

---

## 🎯 IMMEDIATE ACTION ITEMS

### MUST DO (Blockers):
1. **Fix admin templates** - Remove canvas_user references
2. **Add ANTHROPIC_API_KEY** - Assignment agent needs it
3. **Switch assignment agent** - Use Claude instead of OpenAI
4. **Clean submission endpoint** - Use canvas_api_token not cookies

### SHOULD DO (Quality):
5. **Deprecate browser_auth.py** - Mark with clear warnings
6. **Update quiz endpoint** - Simplify token loading
7. **Fix docstrings** - Update outdated comments
8. **Update CLAUDE.md** - Record actual state

### NICE TO DO (Future):
9. **Add type hints** - For maintainability
10. **Add tests** - Unit tests for sync pipeline
11. **Clean user_sessions** - Remove legacy cookies

---

## 📈 COMPLETION ESTIMATE

**Current Completion**: 75%
- Phase 1 (Token Auth): 85%
- Phase 2 (Retention): 95%
- Phase 3 (Hardening): 60%

**To Production Ready**: +3 hours
- Fix critical issues: 1.5 hours
- Testing & verification: 1 hour
- CLAUDE.md update: 30 minutes

**To Browser Extension Ready**: +40 hours
- Refactor sync service: 20 hours
- Design extension auth: 10 hours
- Prepare migration path: 10 hours

---

## ✍️ CONCLUSION

The Canvas app is **75% complete and mostly working**. The core architecture (token auth, data sync, cleanup) is solid. However, there are **8 issues** ranging from critical (admin UI bugs, wrong AI provider) to minor (dead code, documentation).

**Recommendation**: Fix the 4 blocking issues (~1.5 hours), then deploy to Railway. The app is safe for 10-100 students to use, and data retention/cleanup is properly implemented.

The path to browser extension migration is clear and feasible within the existing architecture.

---

## 🔄 NEXT PHASE

Begin fixing issues in priority order:
1. Admin template bug (5 min)
2. ANTHROPIC_API_KEY (5 min)
3. Assignment agent API switch (45 min)
4. Submission endpoint cleanup (15 min)
5. Update CLAUDE.md with findings (30 min)
6. Test on local before Railway deployment

Estimated time to production-ready: **3-4 hours**
