import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
FILES_CACHE_DIR = BASE_DIR / "files_cache"   # downloaded files, never deleted on rebuild
DB_PATH = BASE_DIR / "canvas.db"

CANVAS_BASE_URL = "https://kent.instructure.com"
CANVAS_API_URL = f"{CANVAS_BASE_URL}/api/v1"

CANVAS_USERNAME = os.getenv("CANVAS_USERNAME", "")
CANVAS_PASSWORD = os.getenv("CANVAS_PASSWORD", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

try:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    FILES_CACHE_DIR.mkdir(exist_ok=True)
except OSError:
    pass  # Read-only filesystem (e.g. Vercel)
