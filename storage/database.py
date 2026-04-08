"""
PostgreSQL database — lưu dữ liệu Canvas per user.
Mỗi bảng có cột google_id để cô lập dữ liệu theo người dùng.
get_conn() sử dụng thread-local google_id được set bởi set_user_context().
"""
import json
import threading
import psycopg2
import psycopg2.extras
from config import DATABASE_URL


def load_json(val):
    """Safe JSON loader — handles both str (SQLite legacy) and dict/list (PostgreSQL JSONB)."""
    if val is None:
        return {}
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {}

_local = threading.local()


# ── User context ──────────────────────────────────────────────────────────────

def set_user_context(google_id: str):
    """Set google_id cho thread hiện tại."""
    _local.google_id = google_id


def clear_user_context():
    _local.google_id = None


def _gid() -> str:
    gid = getattr(_local, "google_id", None)
    if not gid:
        raise RuntimeError("No user context — call set_user_context() first")
    return gid


def get_current_google_id():
    return getattr(_local, "google_id", None)


# ── Connection wrapper ────────────────────────────────────────────────────────

class PGConn:
    """
    Wrapper mỏng xung quanh psycopg2 connection, cung cấp API giống sqlite3.
    Tự động chuyển '?' → '%s' để code cũ không cần sửa placeholder.
    """
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.close()


def _db_url() -> str:
    """Ensure sslmode=require for Supabase (and other SSL-only hosts)."""
    url = DATABASE_URL
    if "supabase" in url and "sslmode" not in url:
        sep = "&" if "?" in url else "?"
        url = url + sep + "sslmode=require"
    return url


def get_conn() -> PGConn:
    conn = psycopg2.connect(_db_url(), cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=5)
    # Return JSONB columns as raw strings (not auto-parsed dicts)
    # so existing json.loads() calls in the codebase work unchanged.
    psycopg2.extras.register_default_jsonb(conn, loads=lambda x: x)
    return PGConn(conn)


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    """Tạo các bảng Canvas nếu chưa có."""
    conn = get_conn()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS courses (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            name TEXT,
            course_code TEXT,
            enrollment_term_id BIGINT,
            workflow_state TEXT,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assignments (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            course_id BIGINT,
            name TEXT,
            description TEXT,
            due_at TEXT,
            points_possible REAL,
            submission_types TEXT,
            workflow_state TEXT,
            has_submitted_submissions INTEGER DEFAULT 0,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS submissions (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            assignment_id BIGINT,
            course_id BIGINT,
            user_id BIGINT,
            submitted_at TEXT,
            score REAL,
            grade TEXT,
            workflow_state TEXT,
            submission_type TEXT,
            body TEXT,
            url TEXT,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS files (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            course_id BIGINT,
            display_name TEXT,
            filename TEXT,
            content_type TEXT,
            url TEXT,
            size BIGINT,
            local_path TEXT,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS modules (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            course_id BIGINT,
            name TEXT,
            position INTEGER,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS module_items (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            module_id BIGINT,
            course_id BIGINT,
            title TEXT,
            type TEXT,
            content_id BIGINT,
            url TEXT,
            page_url TEXT,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pages (
            google_id TEXT NOT NULL,
            id BIGINT NOT NULL,
            course_id BIGINT,
            title TEXT,
            body TEXT,
            url TEXT,
            updated_at TEXT,
            raw JSONB,
            PRIMARY KEY (google_id, id)
        )
        """,
    ]
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()
    conn.close()


# ── Upserts ───────────────────────────────────────────────────────────────────

def upsert_course(course: dict):
    gid = _gid()
    conn = get_conn()
    conn.execute("""
        INSERT INTO courses (google_id, id, name, course_code, enrollment_term_id, workflow_state, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            name               = EXCLUDED.name,
            course_code        = EXCLUDED.course_code,
            enrollment_term_id = EXCLUDED.enrollment_term_id,
            workflow_state     = EXCLUDED.workflow_state,
            raw                = EXCLUDED.raw
    """, (gid, course["id"], course.get("name"), course.get("course_code"),
          course.get("enrollment_term_id"), course.get("workflow_state"),
          json.dumps(course)))
    conn.commit()
    conn.close()


def upsert_assignment(a: dict):
    gid = _gid()
    conn = get_conn()
    conn.execute("""
        INSERT INTO assignments
            (google_id, id, course_id, name, description, due_at,
             points_possible, submission_types, workflow_state,
             has_submitted_submissions, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            course_id                  = EXCLUDED.course_id,
            name                       = EXCLUDED.name,
            description                = EXCLUDED.description,
            due_at                     = EXCLUDED.due_at,
            points_possible            = EXCLUDED.points_possible,
            submission_types           = EXCLUDED.submission_types,
            workflow_state             = EXCLUDED.workflow_state,
            has_submitted_submissions  = EXCLUDED.has_submitted_submissions,
            raw                        = EXCLUDED.raw
    """, (
        gid, a["id"], a["course_id"], a.get("name", ""),
        a.get("description", ""), a.get("due_at"),
        a.get("points_possible"),
        json.dumps(a.get("submission_types", [])),
        a.get("workflow_state", ""),
        1 if a.get("has_submitted_submissions") else 0,
        json.dumps(a),
    ))
    conn.commit()
    conn.close()


def upsert_submission(s: dict, course_id: int):
    gid = _gid()
    conn = get_conn()
    conn.execute("""
        INSERT INTO submissions
            (google_id, id, assignment_id, course_id, user_id,
             submitted_at, score, grade, workflow_state,
             submission_type, body, url, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            assignment_id   = EXCLUDED.assignment_id,
            course_id       = EXCLUDED.course_id,
            user_id         = EXCLUDED.user_id,
            submitted_at    = EXCLUDED.submitted_at,
            score           = EXCLUDED.score,
            grade           = EXCLUDED.grade,
            workflow_state  = EXCLUDED.workflow_state,
            submission_type = EXCLUDED.submission_type,
            body            = EXCLUDED.body,
            url             = EXCLUDED.url,
            raw             = EXCLUDED.raw
    """, (
        gid, s["id"], s["assignment_id"], course_id,
        s.get("user_id"), s.get("submitted_at"),
        s.get("score"), s.get("grade"),
        s.get("workflow_state", ""), s.get("submission_type", ""),
        s.get("body", ""), s.get("url", ""),
        json.dumps(s),
    ))
    conn.commit()
    conn.close()


def upsert_file(f: dict, course_id: int):
    gid = _gid()
    conn = get_conn()
    conn.execute("""
        INSERT INTO files
            (google_id, id, course_id, display_name, filename,
             content_type, url, size, local_path, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            course_id    = EXCLUDED.course_id,
            display_name = EXCLUDED.display_name,
            filename     = EXCLUDED.filename,
            content_type = EXCLUDED.content_type,
            url          = EXCLUDED.url,
            size         = EXCLUDED.size,
            local_path   = COALESCE(NULLIF(EXCLUDED.local_path, ''), files.local_path),
            raw          = EXCLUDED.raw
    """, (
        gid, f["id"], course_id,
        f.get("display_name", ""), f.get("filename", ""),
        f.get("content_type", ""), f.get("url", ""),
        f.get("size", 0), f.get("local_path", ""),
        json.dumps(f),
    ))
    conn.commit()
    conn.close()


def upsert_module(m: dict, course_id: int):
    gid = _gid()
    conn = get_conn()
    conn.execute("""
        INSERT INTO modules (google_id, id, course_id, name, position, raw)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            course_id = EXCLUDED.course_id,
            name      = EXCLUDED.name,
            position  = EXCLUDED.position,
            raw       = EXCLUDED.raw
    """, (gid, m["id"], course_id, m.get("name", ""),
          m.get("position", 0), json.dumps(m)))
    conn.commit()
    conn.close()


def upsert_module_item(item: dict, module_id: int, course_id: int):
    gid = _gid()
    conn = get_conn()
    conn.execute("""
        INSERT INTO module_items
            (google_id, id, module_id, course_id, title, type,
             content_id, url, page_url, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            module_id  = EXCLUDED.module_id,
            course_id  = EXCLUDED.course_id,
            title      = EXCLUDED.title,
            type       = EXCLUDED.type,
            content_id = EXCLUDED.content_id,
            url        = EXCLUDED.url,
            page_url   = EXCLUDED.page_url,
            raw        = EXCLUDED.raw
    """, (
        gid, item["id"], module_id, course_id,
        item.get("title", ""), item.get("type", ""),
        item.get("content_id"), item.get("html_url", ""),
        item.get("page_url", ""), json.dumps(item),
    ))
    conn.commit()
    conn.close()


def upsert_page(p: dict, course_id: int):
    gid = _gid()
    page_id = p.get("page_id") or p.get("id", 0)
    conn = get_conn()
    conn.execute("""
        INSERT INTO pages
            (google_id, id, course_id, title, body, url, updated_at, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (google_id, id) DO UPDATE SET
            course_id  = EXCLUDED.course_id,
            title      = EXCLUDED.title,
            body       = EXCLUDED.body,
            url        = EXCLUDED.url,
            updated_at = EXCLUDED.updated_at,
            raw        = EXCLUDED.raw
    """, (
        gid, page_id, course_id,
        p.get("title", ""), p.get("body", ""),
        p.get("url", ""), p.get("updated_at"),
        json.dumps(p),
    ))
    conn.commit()
    conn.close()


# ── Queries ───────────────────────────────────────────────────────────────────

def get_courses() -> list:
    gid = _gid()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM courses WHERE google_id = %s ORDER BY name", (gid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assignments(course_id: int = None) -> list:
    gid = _gid()
    conn = get_conn()
    if course_id:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE google_id = %s AND course_id = %s ORDER BY due_at",
            (gid, course_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE google_id = %s ORDER BY due_at", (gid,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assignment(assignment_id: int):
    gid = _gid()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM assignments WHERE google_id = %s AND id = %s",
        (gid, assignment_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_submission(assignment_id: int):
    gid = _gid()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM submissions WHERE google_id = %s AND assignment_id = %s",
        (gid, assignment_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_modules(course_id: int) -> list:
    gid = _gid()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM modules WHERE google_id = %s AND course_id = %s ORDER BY position",
        (gid, course_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_module_items(module_id: int) -> list:
    gid = _gid()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM module_items WHERE google_id = %s AND module_id = %s ORDER BY id",
        (gid, module_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_files(course_id: int) -> list:
    gid = _gid()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM files WHERE google_id = %s AND course_id = %s",
        (gid, course_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
