"""
User registry — lưu Google account + Canvas credentials per user.
Dùng chung PostgreSQL database (DATABASE_URL).
"""
import os
import base64
import json
from pathlib import Path
import psycopg2
import psycopg2.extras
from cryptography.fernet import Fernet
from config import BASE_DIR, DATABASE_URL

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _get_fernet() -> Fernet:
    """
    Derive a stable Fernet key from FLASK_SECRET_KEY env var so it
    survives container restarts/redeploys on Railway.
    Falls back to a file-based key for local dev.
    """
    secret = os.getenv("FLASK_SECRET_KEY", "")
    if secret:
        # Fernet key must be 32 url-safe base64 bytes
        raw = secret.encode()[:32].ljust(32, b"0")
        key = base64.urlsafe_b64encode(raw)
        return Fernet(key)
    # Local fallback: file-based key
    key_file = DATA_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
    return Fernet(key_file.read_bytes())


def _db_url() -> str:
    url = DATABASE_URL
    if "supabase" in url and "sslmode" not in url:
        sep = "&" if "?" in url else "?"
        url = url + sep + "sslmode=require"
    return url


def get_users_conn():
    """Connect to DB with timeout to prevent hanging."""
    conn = psycopg2.connect(_db_url(), cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=5)
    return conn


def _exec(conn, sql: str, params=()):
    """Helper: execute with auto ? → %s conversion."""
    cur = conn.cursor()
    cur.execute(sql.replace("?", "%s"), params)
    return cur


def init_users_db():
    conn = get_users_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            google_id           TEXT PRIMARY KEY,
            email               TEXT UNIQUE NOT NULL,
            name                TEXT,
            picture             TEXT,
            canvas_api_token    BYTEA,
            canvas_linked       INTEGER DEFAULT 0,
            is_admin            INTEGER DEFAULT 0,
            is_banned           INTEGER DEFAULT 0,
            sync_status         TEXT DEFAULT 'never',
            sync_at             TEXT,
            last_sync_at        TEXT,
            last_accessed_at    TEXT,
            created_at          TEXT DEFAULT (to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            google_id     TEXT PRIMARY KEY,
            cookies_json  TEXT,
            api_token     TEXT,
            updated_at    TEXT DEFAULT (to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')),
            FOREIGN KEY (google_id) REFERENCES users(google_id)
        )
    """)

    # Add missing columns (safe to run on existing DB)
    for col, definition in [
        ("is_admin",        "INTEGER DEFAULT 0"),
        ("is_banned",       "INTEGER DEFAULT 0"),
        ("sync_status",     "TEXT DEFAULT 'never'"),
        ("sync_at",         "TEXT"),
        ("last_sync_at",    "TEXT"),
        ("last_accessed_at","TEXT"),
        ("canvas_api_token","BYTEA"),
    ]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}")
        except Exception:
            pass

    # Drop old password columns if they exist (optional, for cleanup)
    for col in ["canvas_user", "canvas_pass"]:
        try:
            cur.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {col}")
        except Exception:
            pass

    conn.commit()
    cur.close()
    conn.close()


# ── CRUD ───────────────────────────────────────────────────────────────────────

def upsert_google_user(google_id: str, email: str, name: str, picture: str):
    conn = get_users_conn()
    _exec(conn, """
        INSERT INTO users (google_id, email, name, picture)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET
            email=EXCLUDED.email, name=EXCLUDED.name, picture=EXCLUDED.picture
    """, (google_id, email, name, picture))
    conn.commit()
    conn.close()


def get_user(google_id: str):
    conn = get_users_conn()
    cur = _exec(conn, "SELECT * FROM users WHERE google_id=?", (google_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def set_canvas_api_token(google_id: str, api_token: str):
    """Store Canvas API token (encrypted with Fernet)."""
    f = _get_fernet()
    encrypted = f.encrypt(api_token.encode())
    conn = get_users_conn()
    _exec(conn, """
        UPDATE users SET canvas_api_token=?, canvas_linked=1,
                        last_accessed_at=to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS')
        WHERE google_id=?
    """, (psycopg2.Binary(encrypted), google_id))
    conn.commit()
    conn.close()


def get_canvas_api_token(google_id: str) -> str:
    """Retrieve and decrypt Canvas API token."""
    conn = get_users_conn()
    cur = _exec(conn, "SELECT canvas_api_token FROM users WHERE google_id=?", (google_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["canvas_api_token"]:
        return ""
    f = _get_fernet()
    try:
        encrypted_token = bytes(row["canvas_api_token"])
        token = f.decrypt(encrypted_token).decode()
        return token
    except Exception:
        return ""


def get_canvas_credentials(google_id: str):
    """
    Legacy function for backward compatibility.
    Returns (username, password) tuple - always returns (None, "") now.
    New code should use get_canvas_api_token() instead.
    """
    return None, ""


def save_user_session(google_id: str, cookies: list, api_token: str):
    conn = get_users_conn()
    _exec(conn, """
        INSERT INTO user_sessions (google_id, cookies_json, api_token, updated_at)
        VALUES (?, ?, ?, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))
        ON CONFLICT(google_id) DO UPDATE SET
            cookies_json=EXCLUDED.cookies_json,
            api_token=EXCLUDED.api_token,
            updated_at=EXCLUDED.updated_at
    """, (google_id, json.dumps(cookies), api_token))
    conn.commit()
    conn.close()


def load_user_session(google_id: str):
    conn = get_users_conn()
    cur = _exec(conn, "SELECT cookies_json, api_token FROM user_sessions WHERE google_id=?", (google_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None, ""
    cookies = json.loads(row["cookies_json"]) if row["cookies_json"] else None
    return cookies, row["api_token"] or ""


# ── Admin management ──────────────────────────────────────────────────────────

def get_all_users() -> list:
    conn = get_users_conn()
    cur = _exec(conn,
        "SELECT u.*, s.updated_at as session_at FROM users u "
        "LEFT JOIN user_sessions s ON s.google_id = u.google_id "
        "ORDER BY u.created_at DESC"
    )
    rows = cur.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("canvas_pass", None)
        result.append(d)
    return result


def set_admin(google_id: str, value: bool):
    conn = get_users_conn()
    _exec(conn, "UPDATE users SET is_admin=? WHERE google_id=?", (1 if value else 0, google_id))
    conn.commit()
    conn.close()


def set_banned(google_id: str, value: bool):
    conn = get_users_conn()
    _exec(conn, "UPDATE users SET is_banned=? WHERE google_id=?", (1 if value else 0, google_id))
    conn.commit()
    conn.close()


def delete_user(google_id: str):
    conn = get_users_conn()
    _exec(conn, "DELETE FROM user_sessions WHERE google_id=?", (google_id,))
    _exec(conn, "DELETE FROM users WHERE google_id=?", (google_id,))
    conn.commit()
    conn.close()


def update_sync_status(google_id: str, status: str):
    """status: 'syncing' | 'done' | 'error:<msg>'"""
    conn = get_users_conn()
    _exec(conn,
        "UPDATE users SET sync_status=?, sync_at=to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS') WHERE google_id=?",
        (status, google_id)
    )
    conn.commit()
    conn.close()


def update_user_last_sync(google_id: str):
    """Update last_sync_at and last_accessed_at to now."""
    conn = get_users_conn()
    _exec(conn,
        "UPDATE users SET last_sync_at=to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), "
        "last_accessed_at=to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS') WHERE google_id=?",
        (google_id,)
    )
    conn.commit()
    conn.close()


def update_user_activity(google_id: str):
    """Update last_accessed_at to now (track any user activity)."""
    conn = get_users_conn()
    _exec(conn,
        "UPDATE users SET last_accessed_at=to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS') WHERE google_id=?",
        (google_id,)
    )
    conn.commit()
    conn.close()


# ── Per-user file storage paths ───────────────────────────────────────────────

def user_data_dir(google_id: str) -> Path:
    d = DATA_DIR / google_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_downloads_dir(google_id: str) -> Path:
    d = user_data_dir(google_id) / "downloads"
    d.mkdir(exist_ok=True)
    return d


def user_files_cache_dir(google_id: str) -> Path:
    d = user_data_dir(google_id) / "files_cache"
    d.mkdir(exist_ok=True)
    return d


def user_screenshots_dir(google_id: str) -> Path:
    d = user_data_dir(google_id) / "screenshots"
    d.mkdir(exist_ok=True)
    return d
