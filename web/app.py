"""
Canvas Web Dashboard — multi-user Flask app.
Each user authenticates via Google OAuth, links one Canvas account,
and gets an isolated SQLite DB + file storage.
"""
import sys
import json
import os
import functools
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import (Flask, render_template, request, jsonify, redirect,
                   url_for, abort, Response, stream_with_context, session)
from html.parser import HTMLParser
from config import FLASK_SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from storage.users import init_users_db
from storage.database import init_db, load_json

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Trust Railway/proxy HTTPS headers
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# ── Google OAuth ───────────────────────────────────────────────────────────────
from authlib.integrations.flask_client import OAuth
oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

try:
    init_users_db()
    init_db()
except Exception as _db_err:
    import traceback
    print(f"[startup] DB init failed: {_db_err}", flush=True)
    traceback.print_exc()

# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return "ok", 200

# ── Per-request user context ──────────────────────────────────────────────────

def _setup_user_context(google_id: str):
    """Set thread-local DB path + file dirs for this user."""
    from storage.database import set_user_context
    from config import set_user_paths
    set_user_context(google_id)
    set_user_paths(google_id)


def login_required(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        google_id = session.get("google_id")
        if not google_id:
            return redirect(url_for("login_page"))
        _setup_user_context(google_id)
        # If Canvas not linked yet → redirect to setup (except setup routes)
        from storage.users import get_user
        user = get_user(google_id)
        if not user:
            return redirect(url_for("login_page"))
        if user.get("is_banned"):
            session.clear()
            return render_template("login.html",
                error="Your account has been suspended. Contact the administrator.")
        if not user.get("canvas_linked"):
            return redirect(url_for("setup_canvas_get"))
        return f(*args, **kwargs)
    return wrapped


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route("/login")
def login_page():
    if session.get("google_id"):
        return redirect(url_for("dashboard"))
    return render_template("login.html", error=request.args.get("error"))


@app.route("/auth/google")
def auth_google():
    if not GOOGLE_CLIENT_ID:
        return redirect(url_for("login_page", error="Google OAuth chưa cấu hình. Thêm GOOGLE_CLIENT_ID vào .env"))
    redirect_uri = url_for("auth_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def auth_google_callback():
    try:
        token = oauth.google.authorize_access_token()
        info  = token.get("userinfo") or oauth.google.parse_id_token(token)
    except Exception as e:
        return redirect(url_for("login_page", error=f"Google login failed: {e}"))

    google_id = info["sub"]
    email     = info.get("email", "")
    name      = info.get("name", "")
    picture   = info.get("picture", "")

    from storage.users import upsert_google_user, get_user
    upsert_google_user(google_id, email, name, picture)

    session["google_id"] = google_id
    session["user_name"] = name
    session["user_pic"]  = picture

    user = get_user(google_id)
    if not user or not user.get("canvas_linked"):
        return redirect(url_for("setup_canvas_get"))
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ── Canvas setup (one-time) ───────────────────────────────────────────────────

@app.route("/setup/canvas")
def setup_canvas_get():
    google_id = session.get("google_id")
    if not google_id:
        return redirect(url_for("login_page"))
    from storage.users import get_user
    user = get_user(google_id)
    return render_template("setup_canvas.html", user=user or {}, error=None)


@app.route("/setup/canvas/reset")
def setup_canvas_reset():
    """Clear canvas_linked so user can re-enter credentials."""
    google_id = session.get("google_id")
    if not google_id:
        return redirect(url_for("login_page"))
    from storage.users import get_users_conn, _exec
    conn = get_users_conn()
    _exec(conn, "UPDATE users SET canvas_linked=0, canvas_user=NULL, canvas_pass=NULL WHERE google_id=?", (google_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("setup_canvas_get"))


@app.route("/setup/canvas", methods=["POST"])
def setup_canvas_post():
    google_id = session.get("google_id")
    if not google_id:
        return redirect(url_for("login_page"))

    canvas_user = request.form.get("canvas_user", "").strip()
    canvas_pass = request.form.get("canvas_pass", "").strip()

    if not canvas_user or not canvas_pass:
        from storage.users import get_user
        return render_template("setup_canvas.html",
                               user=get_user(google_id) or {},
                               error="Vui lòng nhập FlashLine ID và password.")

    from storage.users import set_canvas_credentials
    set_canvas_credentials(google_id, canvas_user, canvas_pass)

    _setup_user_context(google_id)
    _trigger_sync(google_id)

    return redirect(url_for("dashboard"))


def _trigger_sync(google_id: str):
    """Run Canvas sync in a background thread."""
    import threading
    import os

    # On local dev (no RAILWAY_ENVIRONMENT), run browser visible so user can handle MFA
    is_production = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("HEADLESS_BROWSER"))
    headless = is_production

    def _run():
        _setup_user_context(google_id)
        from storage.users import update_sync_status
        try:
            update_sync_status(google_id, "syncing")
            from storage.users import get_canvas_credentials, save_user_session
            from storage.database import init_db
            from auth.browser_auth import login
            from api.canvas_client import CanvasClient
            from sync.courses import sync_courses
            from sync.assignments import sync_assignments
            from sync.files import sync_files
            from sync.modules import sync_modules
            from sync.pages_deep import sync_pages_deep
            from sync.organizer import build_folders

            username, password = get_canvas_credentials(google_id)
            if not username or not password:
                update_sync_status(google_id, "error:No Canvas credentials saved.")
                return

            cookies, api_token = login(username, password, headless=headless)
            if not cookies and not api_token:
                update_sync_status(google_id, "error:Login failed. Check credentials.")
                return

            save_user_session(google_id, cookies or [], api_token or "")

            init_db()
            client = CanvasClient(cookies=cookies, api_token=api_token)
            courses = sync_courses(client)
            sync_assignments(client, courses)
            sync_files(client, courses, download=True)
            sync_modules(client, courses)
            sync_pages_deep(cookies or [], api_token=api_token or "")
            build_folders()
            update_sync_status(google_id, "done")
        except Exception as e:
            update_sync_status(google_id, f"error:{e}")
            print(f"[sync error {google_id}]: {e}")

    threading.Thread(target=_run, daemon=True).start()


@app.route("/api/sync", methods=["POST"])
@login_required
def api_resync():
    """Re-sync Canvas data for the current user."""
    google_id = session["google_id"]
    _trigger_sync(google_id)
    return jsonify({"success": True, "message": "Sync đang chạy nền..."})


@app.route("/api/sync_status")
@login_required
def api_sync_status():
    """Return current sync_status for polling."""
    from storage.users import get_user
    user = get_user(session["google_id"])
    return jsonify({"status": user.get("sync_status", "never") if user else "never"})


# ── Helpers ───────────────────────────────────────────────────────────────────

COURSE_COLORS = [
    "#E66000", "#0770A3", "#127A1B", "#8B2FA8", "#C41E3A",
    "#D4690A", "#1664A7", "#206B26", "#6B21A8", "#B91C1C",
    "#0E7E6B", "#B45309", "#1D4ED8", "#065F46", "#7C3AED",
]

def course_color(course_id: int) -> str:
    return COURSE_COLORS[course_id % len(COURSE_COLORS)]


class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
    def handle_data(self, d):
        self.result.append(d)
    def get_text(self):
        return " ".join(self.result)

def strip_html(html: str) -> str:
    if not html:
        return ""
    s = HTMLStripper()
    s.feed(html)
    return s.get_text().strip()


def fmt_date(dt: str) -> str:
    if not dt:
        return "No due date"
    try:
        from datetime import datetime
        d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return d.strftime("%b %d, %Y at %I:%M %p")
    except Exception:
        return dt[:16].replace("T", " ")


def submission_status(sub, assignment):
    if not sub:
        due = assignment.get("due_at", "")
        if due:
            from datetime import datetime, timezone
            try:
                d = datetime.fromisoformat(due.replace("Z", "+00:00"))
                if d < datetime.now(timezone.utc):
                    return "Missing", "badge-missing"
            except Exception:
                pass
        return "Not submitted", "badge-gray"
    state = sub.get("workflow_state", "")
    if state == "graded":
        score = sub.get("score")
        pts   = assignment.get("points_possible")
        if score is not None and pts:
            return f"{score}/{pts}", "badge-graded"
        return "Graded", "badge-graded"
    if state == "submitted":
        return "Submitted", "badge-submitted"
    if state == "pending_review":
        return "Pending Review", "badge-submitted"
    return state.replace("_", " ").title(), "badge-gray"


def _current_user():
    return {
        "name":    session.get("user_name", ""),
        "picture": session.get("user_pic",  ""),
        "email":   session.get("google_id", ""),
    }


# ── Main routes ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    from storage.database import get_courses, get_conn, get_current_google_id
    courses = get_courses()
    gid = get_current_google_id()
    for c in courses:
        c["color"] = course_color(c["id"])
        conn = get_conn()
        c["assignment_count"] = conn.execute(
            "SELECT COUNT(*) as n FROM assignments WHERE google_id=? AND course_id=?",
            (gid, c["id"])
        ).fetchone()["n"]
        c["upcoming"] = conn.execute("""
            SELECT COUNT(*) as n FROM assignments a
            LEFT JOIN submissions s ON s.assignment_id = a.id AND s.google_id = a.google_id
            WHERE a.google_id=? AND a.course_id=?
            AND (s.id IS NULL OR s.workflow_state NOT IN ('graded','submitted'))
            AND a.due_at IS NOT NULL
        """, (gid, c["id"])).fetchone()["n"]
        conn.close()
    return render_template("dashboard.html", courses=courses, current_user=_current_user())


@app.route("/courses/<int:course_id>")
@login_required
def course_home(course_id):
    return redirect(url_for("course_modules", course_id=course_id))


@app.route("/courses/<int:course_id>/modules")
@login_required
def course_modules(course_id):
    from storage.database import get_courses, get_modules, get_module_items, get_submission, get_assignment
    courses = get_courses()
    course  = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)
    modules = get_modules(course_id)
    for m in modules:
        m["_items"] = get_module_items(m["id"])
        for item in m["_items"]:
            if item["type"] == "Assignment" and item.get("content_id"):
                sub = get_submission(item["content_id"])
                a   = get_assignment(item["content_id"])
                if a:
                    item["_status_label"], item["_status_class"] = submission_status(sub, a)
                    item["_points"] = a.get("points_possible")
    return render_template("course.html",
        course=course, courses=courses, modules=modules,
        active_tab="modules", current_user=_current_user())


@app.route("/courses/<int:course_id>/assignments")
@login_required
def course_assignments(course_id):
    from storage.database import get_courses, get_assignments, get_submission
    courses = get_courses()
    course  = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)
    assignments = get_assignments(course_id)
    for a in assignments:
        sub = get_submission(a["id"])
        a["_status_label"], a["_status_class"] = submission_status(sub, a)
        a["_sub_types"] = load_json(a.get("submission_types", "[]"))
        a["_due_fmt"]   = fmt_date(a.get("due_at", ""))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    upcoming, past = [], []
    for a in assignments:
        due = a.get("due_at", "")
        if due:
            try:
                d = datetime.fromisoformat(due.replace("Z", "+00:00"))
                (upcoming if d >= now else past).append(a)
            except Exception:
                upcoming.append(a)
        else:
            upcoming.append(a)
    return render_template("course.html",
        course=course, courses=courses,
        upcoming=upcoming, past=past,
        active_tab="assignments", current_user=_current_user())


@app.route("/courses/<int:course_id>/grades")
@login_required
def course_grades(course_id):
    from storage.database import get_courses, get_conn, get_current_google_id
    courses = get_courses()
    course  = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)
    gid = get_current_google_id()
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.id, a.name, a.points_possible, a.due_at, a.submission_types,
               s.score, s.grade, s.workflow_state, s.submitted_at
        FROM assignments a
        LEFT JOIN submissions s ON s.assignment_id = a.id AND s.google_id = a.google_id
        WHERE a.google_id = ? AND a.course_id = ?
        ORDER BY a.due_at
    """, (gid, course_id)).fetchall()
    conn.close()
    grades = [dict(r) for r in rows]
    total_pts  = sum(g["points_possible"] or 0 for g in grades if g.get("score") is not None)
    earned_pts = sum(g["score"] or 0 for g in grades if g.get("score") is not None)
    graded_count = sum(1 for g in grades if g.get("score") is not None)
    for g in grades:
        sub_types = load_json(g.get("submission_types") or "[]")
        g["_is_quiz"]  = "online_quiz" in sub_types
        g["_due_fmt"]  = fmt_date(g.get("due_at", ""))
        if g.get("score") is not None and g.get("points_possible"):
            pct = g["score"] / g["points_possible"] * 100
            g["_pct"] = f"{pct:.0f}%"
            if pct >= 90:   g["_grade_class"] = "grade-a"
            elif pct >= 80: g["_grade_class"] = "grade-b"
            elif pct >= 70: g["_grade_class"] = "grade-c"
            else:           g["_grade_class"] = "grade-d"
        else:
            g["_pct"] = "–"
            g["_grade_class"] = "grade-none"
    return render_template("course.html",
        course=course, courses=courses, grades=grades,
        total_pts=total_pts, earned_pts=earned_pts, graded_count=graded_count,
        active_tab="grades", current_user=_current_user())


@app.route("/courses/<int:course_id>/files")
@login_required
def course_files(course_id):
    from storage.database import get_courses, get_files
    courses = get_courses()
    course  = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)
    files = get_files(course_id)
    for f in files:
        size = f.get("size", 0) or 0
        if size > 1024*1024:  f["_size_fmt"] = f"{size/1024/1024:.1f} MB"
        elif size > 1024:     f["_size_fmt"] = f"{size/1024:.0f} KB"
        else:                 f["_size_fmt"] = f"{size} B"
        f["_has_local"] = bool(f.get("local_path") and __import__("pathlib").Path(f["local_path"]).exists())
    return render_template("course.html",
        course=course, courses=courses, files=files,
        active_tab="files", current_user=_current_user())


@app.route("/courses/<int:course_id>/assignments/<int:assignment_id>")
@login_required
def assignment_detail(course_id, assignment_id):
    from storage.database import get_courses, get_assignment, get_submission
    courses    = get_courses()
    course     = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)
    assignment = get_assignment(assignment_id)
    if not assignment:
        abort(404)
    sub        = get_submission(assignment_id)
    sub_types  = load_json(assignment.get("submission_types", "[]"))
    raw        = load_json(assignment.get("raw", "{}"))
    status_label, status_class = submission_status(sub, assignment)
    is_quiz        = "online_quiz" in sub_types
    is_text        = "online_text_entry" in sub_types
    is_upload      = "online_upload" in sub_types
    is_submittable = is_quiz or is_text or is_upload
    quiz_id        = raw.get("quiz_id")
    from agent.assignment_agent import gather_module_context
    ctx = gather_module_context(assignment_id)
    return render_template("assignment.html",
        course=course, courses=courses,
        assignment=assignment, submission=sub,
        sub_types=sub_types,
        status_label=status_label, status_class=status_class,
        is_quiz=is_quiz, is_text=is_text, is_upload=is_upload,
        is_submittable=is_submittable,
        quiz_id=quiz_id,
        due_fmt=fmt_date(assignment.get("due_at", "")),
        canvas_url=f"https://kent.instructure.com/courses/{course_id}/assignments/{assignment_id}",
        module_name=ctx.get("module_name") or "",
        ctx_sources=ctx.get("sources") or [],
        current_user=_current_user())


@app.route("/courses/<int:course_id>/pages/<path:slug>")
@login_required
def page_view(course_id, slug):
    from storage.database import get_courses, get_conn, get_current_google_id
    courses = get_courses()
    course  = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)
    gid = get_current_google_id()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM pages WHERE google_id=? AND course_id=? AND url=?",
        (gid, course_id, slug)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM pages WHERE google_id=? AND course_id=? AND url LIKE ?",
            (gid, course_id, f"%{slug}%")
        ).fetchone()
    conn.close()
    if not row:
        abort(404)
    return render_template("page_view.html",
        course=course, courses=courses, page=dict(row),
        current_user=_current_user())


# ── AI API endpoints ───────────────────────────────────────────────────────────

@app.route("/api/complete/<int:assignment_id>", methods=["POST"])
@login_required
def api_complete(assignment_id):
    from config import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        return jsonify({"error": "Cần OPENAI_API_KEY trong .env"}), 400
    from storage.database import get_assignment
    if not get_assignment(assignment_id):
        return jsonify({"error": "Assignment not found"}), 404

    def generate():
        import queue, threading
        import json as _json
        q = queue.Queue()

        def cb(msg):
            q.put(("progress", msg))

        def run_ai():
            from agent.assignment_agent import complete_assignment
            try:
                answer = complete_assignment(assignment_id, progress_cb=cb)
                q.put(("done", answer))
            except Exception as e:
                q.put(("error", str(e)))

        threading.Thread(target=run_ai, daemon=True).start()

        while True:
            try:
                kind, val = q.get(timeout=300)
            except queue.Empty:
                yield f"data: {_json.dumps({'type':'error','msg':'Timeout (300s)'})}\n\n"
                break
            if kind == "progress":
                yield f"data: {_json.dumps({'type':'progress','msg':val})}\n\n"
            elif kind == "done":
                yield f"data: {_json.dumps({'type':'done','draft':val or ''})}\n\n"
                break
            elif kind == "error":
                yield f"data: {_json.dumps({'type':'error','msg':val})}\n\n"
                break

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/submit/<int:assignment_id>", methods=["POST"])
@login_required
def api_submit(assignment_id):
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Nội dung trống"}), 400
    from storage.database import get_assignment
    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404
    try:
        from storage.users import load_user_session
        cookies, api_token = load_user_session(session["google_id"])
        if not cookies and not api_token:
            return jsonify({"error": "Session hết hạn. Vào Settings → Re-sync."}), 401
        from api.canvas_client import CanvasClient
        client    = CanvasClient(cookies=cookies, api_token=api_token)
        course_id = assignment["course_id"]
        result    = client.post(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions",
            {"submission": {"submission_type": "online_text_entry", "body": text}},
        )
        return jsonify({"success": True, "submission_id": result.get("id")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/quiz/<int:assignment_id>", methods=["POST"])
@login_required
def api_quiz(assignment_id):
    from config import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        return jsonify({"error": "Cần OPENAI_API_KEY trong .env"}), 400
    from storage.database import get_assignment
    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Not found"}), 404
    raw     = load_json(assignment.get("raw", "{}"))
    quiz_id = raw.get("quiz_id")
    if not quiz_id:
        return jsonify({"error": "Not a quiz assignment"}), 400
    from storage.users import load_user_session
    cookies, api_token = load_user_session(session["google_id"])
    if not api_token and not cookies:
        return jsonify({"error": "Chưa có session. Vào dashboard → Sync Canvas trước."}), 401

    google_id = session["google_id"]

    def generate():
        import queue, threading
        import json as _json
        q = queue.Queue()

        def cb(msg):
            q.put(("progress", msg))

        def run_quiz():
            _setup_user_context(google_id)
            from agent.quiz_agent import solve_quiz_api
            try:
                result = solve_quiz_api(
                    course_id=assignment["course_id"],
                    quiz_id=quiz_id,
                    assignment_id=assignment_id,
                    api_token=api_token,
                    cookies=cookies,
                    progress_cb=cb,
                )
                q.put(("done", result))
            except Exception as e:
                q.put(("error", str(e)))

        threading.Thread(target=run_quiz, daemon=True).start()

        while True:
            try:
                kind, val = q.get(timeout=600)
            except queue.Empty:
                yield f"data: {_json.dumps({'type':'error','msg':'Timeout (600s)'})}\n\n"
                break
            if kind == "progress":
                yield f"data: {_json.dumps({'type':'progress','msg':val})}\n\n"
            elif kind == "done":
                yield f"data: {_json.dumps({'type':'done','draft':val or ''})}\n\n"
                break
            elif kind == "error":
                yield f"data: {_json.dumps({'type':'error','msg':val})}\n\n"
                break

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


from web.admin import admin_bp  # noqa
app.register_blueprint(admin_bp)

if __name__ == "__main__":
    app.run(debug=True, port=8080, host="0.0.0.0")
