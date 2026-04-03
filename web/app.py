"""
Canvas Web Dashboard - Flask app
Mirrors Canvas LMS interface using local SQLite data.
"""
import sys
import json
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from html.parser import HTMLParser
from storage.database import (
    get_conn, get_courses, get_assignments, get_assignment,
    get_submission, get_modules, get_module_items, get_files,
)

app = Flask(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

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
    """Return (label, color_class) for submission state."""
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
        pts = assignment.get("points_possible")
        if score is not None and pts:
            return f"{score}/{pts}", "badge-graded"
        return "Graded", "badge-graded"
    if state == "submitted":
        return "Submitted", "badge-submitted"
    if state == "pending_review":
        return "Pending Review", "badge-submitted"
    return state.replace("_", " ").title(), "badge-gray"


def get_page_by_slug(course_id: int, slug: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM pages WHERE course_id=? AND url=?", (course_id, slug)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_discussions(course_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM assignments WHERE course_id=? AND submission_types LIKE '%discussion%' ORDER BY due_at",
        (course_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_grades_data(course_id: int):
    """Get assignments with their submission scores."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.id, a.name, a.points_possible, a.due_at, a.submission_types,
               s.score, s.grade, s.workflow_state, s.submitted_at
        FROM assignments a
        LEFT JOIN submissions s ON s.assignment_id = a.id
        WHERE a.course_id = ?
        ORDER BY a.due_at
    """, (course_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    courses = get_courses()
    # Filter active courses (exclude orientation/resource courses)
    for c in courses:
        c["color"] = course_color(c["id"])
        # Count assignments
        conn = get_conn()
        c["assignment_count"] = conn.execute(
            "SELECT COUNT(*) as n FROM assignments WHERE course_id=?", (c["id"],)
        ).fetchone()["n"]
        # Count upcoming (not submitted, not past due limit)
        c["upcoming"] = conn.execute("""
            SELECT COUNT(*) as n FROM assignments a
            LEFT JOIN submissions s ON s.assignment_id = a.id
            WHERE a.course_id=? AND (s.id IS NULL OR s.workflow_state NOT IN ('graded','submitted'))
            AND a.due_at IS NOT NULL
        """, (c["id"],)).fetchone()["n"]
        conn.close()
    return render_template("dashboard.html", courses=courses)


@app.route("/courses/<int:course_id>")
def course_home(course_id):
    return redirect(url_for("course_modules", course_id=course_id))


@app.route("/courses/<int:course_id>/modules")
def course_modules(course_id):
    courses = get_courses()
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)

    modules = get_modules(course_id)
    for m in modules:
        m["_items"] = get_module_items(m["id"])
        for item in m["_items"]:
            # Attach submission state to Assignment items
            if item["type"] == "Assignment" and item.get("content_id"):
                sub = get_submission(item["content_id"])
                a = get_assignment(item["content_id"])
                if a:
                    item["_status_label"], item["_status_class"] = submission_status(sub, a)
                    item["_points"] = a.get("points_possible")

    return render_template("course.html",
        course=course, courses=courses, modules=modules,
        active_tab="modules"
    )


@app.route("/courses/<int:course_id>/assignments")
def course_assignments(course_id):
    courses = get_courses()
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)

    assignments = get_assignments(course_id)
    for a in assignments:
        sub = get_submission(a["id"])
        a["_status_label"], a["_status_class"] = submission_status(sub, a)
        a["_sub_types"] = json.loads(a.get("submission_types", "[]"))
        a["_due_fmt"] = fmt_date(a.get("due_at", ""))

    # Group by upcoming vs past
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    upcoming, past = [], []
    for a in assignments:
        due = a.get("due_at", "")
        if due:
            try:
                d = datetime.fromisoformat(due.replace("Z", "+00:00"))
                if d >= now:
                    upcoming.append(a)
                else:
                    past.append(a)
            except Exception:
                upcoming.append(a)
        else:
            upcoming.append(a)

    return render_template("course.html",
        course=course, courses=courses,
        upcoming=upcoming, past=past,
        active_tab="assignments"
    )


@app.route("/courses/<int:course_id>/grades")
def course_grades(course_id):
    courses = get_courses()
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)

    grades = get_grades_data(course_id)
    total_pts = sum(g["points_possible"] or 0 for g in grades if g.get("score") is not None)
    earned_pts = sum(g["score"] or 0 for g in grades if g.get("score") is not None)
    graded_count = sum(1 for g in grades if g.get("score") is not None)

    for g in grades:
        sub_types = json.loads(g.get("submission_types") or "[]")
        g["_is_quiz"] = "online_quiz" in sub_types
        g["_due_fmt"] = fmt_date(g.get("due_at", ""))
        if g.get("score") is not None and g.get("points_possible"):
            pct = g["score"] / g["points_possible"] * 100
            g["_pct"] = f"{pct:.0f}%"
            if pct >= 90: g["_grade_class"] = "grade-a"
            elif pct >= 80: g["_grade_class"] = "grade-b"
            elif pct >= 70: g["_grade_class"] = "grade-c"
            else: g["_grade_class"] = "grade-d"
        else:
            g["_pct"] = "–"
            g["_grade_class"] = "grade-none"

    return render_template("course.html",
        course=course, courses=courses, grades=grades,
        total_pts=total_pts, earned_pts=earned_pts, graded_count=graded_count,
        active_tab="grades"
    )


@app.route("/courses/<int:course_id>/files")
def course_files(course_id):
    courses = get_courses()
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)

    files = get_files(course_id)
    for f in files:
        size = f.get("size", 0) or 0
        if size > 1024 * 1024:
            f["_size_fmt"] = f"{size/1024/1024:.1f} MB"
        elif size > 1024:
            f["_size_fmt"] = f"{size/1024:.0f} KB"
        else:
            f["_size_fmt"] = f"{size} B"
        f["_has_local"] = bool(f.get("local_path") and __import__("pathlib").Path(f["local_path"]).exists())

    return render_template("course.html",
        course=course, courses=courses, files=files,
        active_tab="files"
    )


@app.route("/courses/<int:course_id>/assignments/<int:assignment_id>")
def assignment_detail(course_id, assignment_id):
    courses = get_courses()
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)

    assignment = get_assignment(assignment_id)
    if not assignment:
        abort(404)

    sub = get_submission(assignment_id)
    sub_types = json.loads(assignment.get("submission_types", "[]"))
    raw = json.loads(assignment.get("raw", "{}"))

    status_label, status_class = submission_status(sub, assignment)
    is_quiz = "online_quiz" in sub_types
    is_text = "online_text_entry" in sub_types
    is_upload = "online_upload" in sub_types
    is_submittable = is_quiz or is_text or is_upload
    quiz_id = raw.get("quiz_id")

    return render_template("assignment.html",
        course=course, courses=courses,
        assignment=assignment,
        submission=sub,
        sub_types=sub_types,
        status_label=status_label,
        status_class=status_class,
        is_quiz=is_quiz,
        is_text=is_text,
        is_upload=is_upload,
        is_submittable=is_submittable,
        quiz_id=quiz_id,
        due_fmt=fmt_date(assignment.get("due_at", "")),
        canvas_url=f"https://kent.instructure.com/courses/{course_id}/assignments/{assignment_id}",
    )


@app.route("/courses/<int:course_id>/pages/<path:slug>")
def page_view(course_id, slug):
    courses = get_courses()
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        abort(404)
    course["color"] = course_color(course_id)

    page = get_page_by_slug(course_id, slug)
    if not page:
        # Try by title slug
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM pages WHERE course_id=? AND url LIKE ?",
            (course_id, f"%{slug}%")
        ).fetchone()
        conn.close()
        page = dict(row) if row else None

    if not page:
        abort(404)

    return render_template("page_view.html",
        course=course, courses=courses, page=page
    )


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.route("/api/complete/<int:assignment_id>", methods=["POST"])
def api_complete(assignment_id):
    """Call AI to generate answer for an assignment. Returns JSON with text."""
    from config import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        return jsonify({"error": "Cần OPENAI_API_KEY trong .env để dùng tính năng AI"}), 400

    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    try:
        from agent.assignment_agent import complete_assignment
        # complete_assignment uses console output for interactive stuff
        # We capture just the return value
        draft = complete_assignment(assignment_id)
        if draft:
            return jsonify({"draft": draft})
        else:
            return jsonify({"error": "AI không tạo được câu trả lời"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/submit/<int:assignment_id>", methods=["POST"])
def api_submit(assignment_id):
    """Submit text answer to Canvas API."""
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Nội dung trống"}), 400

    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    try:
        from auth.browser_auth import load_saved_cookies, load_saved_token
        from api.canvas_client import CanvasClient
        cookies = load_saved_cookies()
        api_token = load_saved_token()
        if not cookies and not api_token:
            return jsonify({"error": "Chưa có session. Chạy sync trước."}), 401

        client = CanvasClient(cookies=cookies, api_token=api_token)
        course_id = assignment["course_id"]
        result = client.post(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions",
            {"submission": {"submission_type": "online_text_entry", "body": text}},
        )
        return jsonify({"success": True, "submission_id": result.get("id")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/quiz/<int:assignment_id>", methods=["POST"])
def api_quiz(assignment_id):
    """Launch quiz agent in background."""
    assignment = get_assignment(assignment_id)
    if not assignment:
        return jsonify({"error": "Not found"}), 404

    raw = json.loads(assignment.get("raw", "{}"))
    quiz_id = raw.get("quiz_id")
    if not quiz_id:
        return jsonify({"error": "Not a quiz"}), 400

    try:
        from auth.browser_auth import load_saved_cookies
        cookies = load_saved_cookies()
        if not cookies:
            return jsonify({"error": "Chưa có session"}), 401

        import subprocess, sys
        subprocess.Popen([
            sys.executable, "-c",
            f"""
import sys
sys.path.insert(0, '{os.path.dirname(os.path.dirname(__file__))}')
from agent.quiz_agent import solve_quiz
from auth.browser_auth import load_saved_cookies
cookies = load_saved_cookies()
solve_quiz(course_id={assignment['course_id']}, quiz_id={quiz_id},
           assignment_id={assignment_id}, cookies=cookies, headless=False)
"""
        ])
        return jsonify({"success": True, "message": "Quiz agent đang khởi động..."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8080, host="0.0.0.0")
