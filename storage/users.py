"""
User registry — lưu Google account + Canvas credentials per user.
DB: data/users.db (separate from per-user canvas.db)
"""
import sqlite3
import json
from pathlib import Path
from cryptography.fernet import Fernet
from config import BASE_DIR

USERS_DB  = BASE_DIR / "data" / "users.db"
DATA_DIR  = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Encryption key for Canvas passwords (stored in data/secret.key)
_KEY_FILE = DATA_DIR / "secret.key"

def _get_fernet() -> Fernet:
    if not _KEY_FILE.exists():
        _KEY_FILE.write_bytes(Fernet.generate_key())
    return Fernet(_KEY_FILE.read_bytes())


def get_users_conn():
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_users_db():
    conn = get_users_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            google_id     TEXT PRIMARY KEY,
            email         TEXT UNIQUE NOT NULL,
            name          TEXT,
            picture       TEXT,
            canvas_user   TEXT,
            canvas_pass   BLOB,
            canvas_linked INTEGER DEFAULT 0,
            is_admin      INTEGER DEFAULT 0,
            is_banned     INTEGER DEFAULT 0,
            sync_status   TEXT DEFAULT 'never',
            sync_at       TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS user_sessions (
            google_id     TEXT PRIMARY KEY,
            cookies_json  TEXT,
            api_token     TEXT,
            updated_at    TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (google_id) REFERENCES users(google_id)
        );
    """)
    # Migrate existing DB — add columns if missing
    for col, definition in [
        ("is_admin",    "INTEGER DEFAULT 0"),
        ("is_banned",   "INTEGER DEFAULT 0"),
        ("sync_status", "TEXT DEFAULT 'never'"),
        ("sync_at",     "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            pass
    conn.commit()
    conn.close()


# ── CRUD ───────────────────────────────────────────────────────────────────────

def upsert_google_user(google_id: str, email: str, name: str, picture: str):
    conn = get_users_conn()
    conn.execute("""
        INSERT INTO users (google_id, email, name, picture)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET
            email=excluded.email, name=excluded.name, picture=excluded.picture
    """, (google_id, email, name, picture))
    conn.commit()
    conn.close()


def get_user(google_id: str):
    conn = get_users_conn()
    row = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_canvas_credentials(google_id: str, username: str, password: str):
    f = _get_fernet()
    encrypted = f.encrypt(password.encode())
    conn = get_users_conn()
    conn.execute("""
        UPDATE users SET canvas_user=?, canvas_pass=?, canvas_linked=1
        WHERE google_id=?
    """, (username, encrypted, google_id))
    conn.commit()
    conn.close()


def get_canvas_credentials(google_id: str):
    conn = get_users_conn()
    row = conn.execute(
        "SELECT canvas_user, canvas_pass FROM users WHERE google_id=?", (google_id,)
    ).fetchone()
    conn.close()
    if not row or not row["canvas_user"]:
        return None, None
    f = _get_fernet()
    password = f.decrypt(row["canvas_pass"]).decode()
    return row["canvas_user"], password


def save_user_session(google_id: str, cookies: list, api_token: str):
    conn = get_users_conn()
    conn.execute("""
        INSERT INTO user_sessions (google_id, cookies_json, api_token, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(google_id) DO UPDATE SET
            cookies_json=excluded.cookies_json,
            api_token=excluded.api_token,
            updated_at=excluded.updated_at
    """, (google_id, json.dumps(cookies), api_token))
    conn.commit()
    conn.close()


def load_user_session(google_id: str):
    conn = get_users_conn()
    row = conn.execute(
        "SELECT cookies_json, api_token FROM user_sessions WHERE google_id=?", (google_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None, ""
    cookies = json.loads(row["cookies_json"]) if row["cookies_json"] else None
    return cookies, row["api_token"] or ""


# ── Admin management ──────────────────────────────────────────────────────────

def get_all_users() -> list:
    conn = get_users_conn()
    rows = conn.execute(
        "SELECT u.*, s.updated_at as session_at FROM users u "
        "LEFT JOIN user_sessions s ON s.google_id = u.google_id "
        "ORDER BY u.created_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("canvas_pass", None)  # never expose encrypted password
        result.append(d)
    return result


def set_admin(google_id: str, value: bool):
    conn = get_users_conn()
    conn.execute("UPDATE users SET is_admin=? WHERE google_id=?", (1 if value else 0, google_id))
    conn.commit()
    conn.close()


def set_banned(google_id: str, value: bool):
    conn = get_users_conn()
    conn.execute("UPDATE users SET is_banned=? WHERE google_id=?", (1 if value else 0, google_id))
    conn.commit()
    conn.close()


def delete_user(google_id: str):
    conn = get_users_conn()
    conn.execute("DELETE FROM user_sessions WHERE google_id=?", (google_id,))
    conn.execute("DELETE FROM users WHERE google_id=?", (google_id,))
    conn.commit()
    conn.close()


def update_sync_status(google_id: str, status: str):
    """status: 'syncing' | 'done' | 'error:<msg>'"""
    conn = get_users_conn()
    conn.execute(
        "UPDATE users SET sync_status=?, sync_at=datetime('now') WHERE google_id=?",
        (status, google_id)
    )
    conn.commit()
    conn.close()


# ── Per-user data paths ────────────────────────────────────────────────────────

def user_data_dir(google_id: str) -> Path:
    d = DATA_DIR / google_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_db_path(google_id: str) -> Path:
    return user_data_dir(google_id) / "canvas.db"


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
