import os
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
FILES_CACHE_DIR = BASE_DIR / "files_cache"
DB_PATH = BASE_DIR / "canvas.db"

CANVAS_BASE_URL = "https://kent.instructure.com"
CANVAS_API_URL = f"{CANVAS_BASE_URL}/api/v1"

CANVAS_USERNAME = os.getenv("CANVAS_USERNAME", "")
CANVAS_PASSWORD = os.getenv("CANVAS_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # For Claude assignment help
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")  # For GPT-4o quiz feature

DATABASE_URL = os.getenv("DATABASE_URL", "")

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
FLASK_SECRET_KEY     = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())
ADMIN_PASSWORD       = os.getenv("ADMIN_PASSWORD", "admin1234")

try:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    FILES_CACHE_DIR.mkdir(exist_ok=True)
    (BASE_DIR / "data").mkdir(exist_ok=True)
except OSError:
    pass

# ── Per-user path helpers (used by sync code) ──────────────────────────────────
_local = threading.local()

def set_user_paths(google_id: str):
    """Call at start of each request to set per-user directories."""
    from storage.users import user_downloads_dir, user_files_cache_dir, user_screenshots_dir
    _local.google_id      = google_id
    _local.downloads_dir  = user_downloads_dir(google_id)
    _local.files_cache    = user_files_cache_dir(google_id)
    _local.screenshots    = user_screenshots_dir(google_id)


def get_user_downloads_dir() -> Path:
    return getattr(_local, "downloads_dir", DOWNLOADS_DIR)


def get_user_files_cache_dir() -> Path:
    return getattr(_local, "files_cache", FILES_CACHE_DIR)


def get_user_screenshots_dir() -> Path:
    return getattr(_local, "screenshots", BASE_DIR / "screenshots")


def get_current_google_id():
    return getattr(_local, "google_id", None)
