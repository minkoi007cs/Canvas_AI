"""
SQLite database - lưu toàn bộ dữ liệu Canvas local.
"""
import sqlite3
import json
from pathlib import Path
from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Tạo tables nếu chưa có."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY,
            name TEXT,
            course_code TEXT,
            enrollment_term_id INTEGER,
            workflow_state TEXT,
            raw JSON
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY,
            course_id INTEGER,
            name TEXT,
            description TEXT,
            due_at TEXT,
            points_possible REAL,
            submission_types TEXT,
            workflow_state TEXT,
            has_submitted_submissions INTEGER DEFAULT 0,
            raw JSON,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY,
            assignment_id INTEGER,
            course_id INTEGER,
            user_id INTEGER,
            submitted_at TEXT,
            score REAL,
            grade TEXT,
            workflow_state TEXT,
            submission_type TEXT,
            body TEXT,
            url TEXT,
            raw JSON,
            FOREIGN KEY (assignment_id) REFERENCES assignments(id)
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            course_id INTEGER,
            display_name TEXT,
            filename TEXT,
            content_type TEXT,
            url TEXT,
            size INTEGER,
            local_path TEXT,
            raw JSON,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS modules (
            id INTEGER PRIMARY KEY,
            course_id INTEGER,
            name TEXT,
            position INTEGER,
            raw JSON,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS module_items (
            id INTEGER PRIMARY KEY,
            module_id INTEGER,
            course_id INTEGER,
            title TEXT,
            type TEXT,
            content_id INTEGER,
            url TEXT,
            page_url TEXT,
            raw JSON,
            FOREIGN KEY (module_id) REFERENCES modules(id)
        );

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            course_id INTEGER,
            title TEXT,
            body TEXT,
            url TEXT,
            updated_at TEXT,
            raw JSON,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );
    """)
    conn.commit()
    conn.close()


def upsert_course(course: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO courses (id, name, course_code, enrollment_term_id, workflow_state, raw)
        VALUES (:id, :name, :course_code, :enrollment_term_id, :workflow_state, :raw)
    """, {**course, "raw": json.dumps(course)})
    conn.commit()
    conn.close()


def upsert_assignment(a: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO assignments
        (id, course_id, name, description, due_at, points_possible, submission_types, workflow_state, has_submitted_submissions, raw)
        VALUES (:id, :course_id, :name, :description, :due_at, :points_possible, :submission_types, :workflow_state, :has_submitted_submissions, :raw)
    """, {
        "id": a["id"],
        "course_id": a["course_id"],
        "name": a.get("name", ""),
        "description": a.get("description", ""),
        "due_at": a.get("due_at"),
        "points_possible": a.get("points_possible"),
        "submission_types": json.dumps(a.get("submission_types", [])),
        "workflow_state": a.get("workflow_state", ""),
        "has_submitted_submissions": 1 if a.get("has_submitted_submissions") else 0,
        "raw": json.dumps(a),
    })
    conn.commit()
    conn.close()


def upsert_submission(s: dict, course_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO submissions
        (id, assignment_id, course_id, user_id, submitted_at, score, grade, workflow_state, submission_type, body, url, raw)
        VALUES (:id, :assignment_id, :course_id, :user_id, :submitted_at, :score, :grade, :workflow_state, :submission_type, :body, :url, :raw)
    """, {
        "id": s["id"],
        "assignment_id": s["assignment_id"],
        "course_id": course_id,
        "user_id": s.get("user_id"),
        "submitted_at": s.get("submitted_at"),
        "score": s.get("score"),
        "grade": s.get("grade"),
        "workflow_state": s.get("workflow_state", ""),
        "submission_type": s.get("submission_type", ""),
        "body": s.get("body", ""),
        "url": s.get("url", ""),
        "raw": json.dumps(s),
    })
    conn.commit()
    conn.close()


def upsert_file(f: dict, course_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO files (id, course_id, display_name, filename, content_type, url, size, local_path, raw)
        VALUES (:id, :course_id, :display_name, :filename, :content_type, :url, :size, :local_path, :raw)
    """, {
        "id": f["id"],
        "course_id": course_id,
        "display_name": f.get("display_name", ""),
        "filename": f.get("filename", ""),
        "content_type": f.get("content_type", ""),
        "url": f.get("url", ""),
        "size": f.get("size", 0),
        "local_path": f.get("local_path", ""),
        "raw": json.dumps(f),
    })
    conn.commit()
    conn.close()


def upsert_module_item(item: dict, module_id: int, course_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO module_items
        (id, module_id, course_id, title, type, content_id, url, page_url, raw)
        VALUES (:id, :module_id, :course_id, :title, :type, :content_id, :url, :page_url, :raw)
    """, {
        "id": item["id"],
        "module_id": module_id,
        "course_id": course_id,
        "title": item.get("title", ""),
        "type": item.get("type", ""),
        "content_id": item.get("content_id"),
        "url": item.get("html_url", ""),
        "page_url": item.get("page_url", ""),
        "raw": json.dumps(item),
    })
    conn.commit()
    conn.close()


def upsert_module(m: dict, course_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO modules (id, course_id, name, position, raw)
        VALUES (:id, :course_id, :name, :position, :raw)
    """, {"id": m["id"], "course_id": course_id, "name": m.get("name", ""), "position": m.get("position", 0), "raw": json.dumps(m)})
    conn.commit()
    conn.close()


def upsert_page(p: dict, course_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO pages (id, course_id, title, body, url, updated_at, raw)
        VALUES (:id, :course_id, :title, :body, :url, :updated_at, :raw)
    """, {
        "id": p.get("page_id") or p.get("id", 0),
        "course_id": course_id,
        "title": p.get("title", ""),
        "body": p.get("body", ""),
        "url": p.get("url", ""),
        "updated_at": p.get("updated_at"),
        "raw": json.dumps(p),
    })
    conn.commit()
    conn.close()


def get_courses() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM courses ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assignments(course_id: int = None) -> list:
    conn = get_conn()
    if course_id:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE course_id=? ORDER BY due_at", (course_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM assignments ORDER BY due_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assignment(assignment_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_submission(assignment_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM submissions WHERE assignment_id=?", (assignment_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_modules(course_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM modules WHERE course_id=? ORDER BY position", (course_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_module_items(module_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM module_items WHERE module_id=? ORDER BY id", (module_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_files(course_id: int) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM files WHERE course_id=?", (course_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
