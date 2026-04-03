"""
Fetch individual page bodies by slug and download embedded files.
Canvas /courses/X/pages list returns 404 for some courses,
so we fetch each page individually via its slug from module_items.
"""
import re
import json
import requests
from pathlib import Path
from html.parser import HTMLParser
from rich.console import Console
from storage.database import get_conn, upsert_page, upsert_file
from config import CANVAS_BASE_URL, DOWNLOADS_DIR, FILES_CACHE_DIR

console = Console()

VIDEO_DOMAINS = {"youtube.com", "youtu.be", "kaltura", "mediasite",
                 "yuja.com", "panopto.com", "vimeo.com"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpeg"}

SKIP_EXTS = VIDEO_EXTS | {".mp3", ".wav", ".m4a", ".aac"}


# ─── Link extractor ───────────────────────────────────────────────────────────

class LinkExtractor(HTMLParser):
    """Extract hrefs, srcs, and iframes from HTML."""
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []       # (url, text_hint, tag)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href", "")
            if href and not href.startswith("javascript:") and not href.startswith("#"):
                self.links.append((href, "", "a"))
        elif tag in ("img", "source"):
            src = attrs.get("src", "")
            if src and not src.startswith("data:"):
                self.links.append((src, "", tag))
        elif tag == "iframe":
            src = attrs.get("src", "")
            if src:
                self.links.append((src, "", "iframe"))


def extract_links(html, base_url):
    p = LinkExtractor(base_url)
    p.feed(html or "")
    return p.links


# ─── URL classifiers ──────────────────────────────────────────────────────────

def _is_video_url(url):
    url_lower = url.lower()
    if any(d in url_lower for d in VIDEO_DOMAINS):
        return True
    ext = Path(url.split("?")[0]).suffix.lower()
    return ext in VIDEO_EXTS


def _canvas_file_id(url, course_id):
    """Extract Canvas file ID from a URL like /courses/X/files/12345 or /files/12345."""
    m = re.search(r"/files/(\d+)", url)
    return int(m.group(1)) if m else None


def _is_downloadable(url):
    """True if URL looks like a downloadable file (not a web page)."""
    path = url.split("?")[0].lower()
    ext = Path(path).suffix
    downloadable = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx",
                    ".xls", ".zip", ".png", ".jpg", ".jpeg", ".gif",
                    ".txt", ".csv"}
    if ext in downloadable:
        return True
    if "/download" in url or "/files/" in url:
        return True
    return False


# ─── Main sync function ────────────────────────────────────────────────────────

def sync_pages_deep(cookies):
    """
    Fetch all page bodies that are referenced in module items.
    Also parse each page to find and download embedded files.
    """
    session_cookies = {c["name"]: c["value"]
                       for c in cookies if "instructure" in c.get("domain", "")}
    headers = {"User-Agent": "Mozilla/5.0"}

    conn = get_conn()
    # Get all page-type module items that don't yet have body in pages table
    rows = conn.execute("""
        SELECT DISTINCT mi.course_id, mi.page_url
        FROM module_items mi
        WHERE mi.type = 'Page' AND mi.page_url != ''
        AND NOT EXISTS (
            SELECT 1 FROM pages p
            WHERE p.url = mi.page_url AND p.course_id = mi.course_id
            AND p.body IS NOT NULL AND p.body != ''
        )
    """).fetchall()
    conn.close()

    console.print(f"[blue]Fetching {len(rows)} pages...[/blue]")

    for row in rows:
        course_id = row["course_id"]
        slug = row["page_url"]
        url = f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/pages/{slug}"

        try:
            r = requests.get(url, cookies=session_cookies, headers=headers, timeout=15)
            if not r.ok:
                continue
            data = r.json()
            upsert_page(data, course_id)
            body_len = len(data.get("body") or "")
            console.print(f"  [dim]{slug[:40]} ({body_len} chars)[/dim]")
        except Exception as e:
            console.print(f"  [red]Error {slug}: {e}[/red]")

    console.print("[green]✓ Pages fetched[/green]")

    # Now download files embedded in pages
    _download_page_files(session_cookies, headers)


def _download_page_files(session_cookies, headers):
    """Parse page HTML bodies, find embedded files, download them."""
    conn = get_conn()
    pages = conn.execute(
        "SELECT id, course_id, title, url, body FROM pages WHERE body != '' AND body IS NOT NULL"
    ).fetchall()
    conn.close()

    console.print(f"[blue]Scanning {len(pages)} page bodies for embedded files...[/blue]")
    total_downloaded = 0

    for page in pages:
        course_id = page["course_id"]
        body = page["body"] or ""
        if not body:
            continue

        links = extract_links(body, CANVAS_BASE_URL)
        file_links = []

        for url, _, tag in links:
            if not url:
                continue
            # Skip video iframes / video urls
            if _is_video_url(url):
                continue
            # Skip anchor-only, mailto
            if url.startswith("mailto:") or url.startswith("#"):
                continue
            # Canvas file links
            fid = _canvas_file_id(url, course_id)
            if fid:
                file_links.append(("canvas_file", fid, url))
            elif tag in ("img", "source") and _is_downloadable(url):
                file_links.append(("direct", None, url))

        if not file_links:
            continue

        # Download each file
        for kind, fid, url in file_links:
            if kind == "canvas_file":
                _ensure_canvas_file(fid, course_id, session_cookies, headers)
                total_downloaded += 1

    console.print(f"[green]✓ Processed {total_downloaded} embedded file references[/green]")


def _ensure_canvas_file(file_id, course_id, session_cookies, headers):
    """Fetch file metadata and download if not already local."""
    conn = get_conn()
    existing = conn.execute(
        "SELECT local_path FROM files WHERE id=?", (file_id,)
    ).fetchone()
    conn.close()

    if existing and existing["local_path"] and Path(existing["local_path"]).exists():
        return  # Already downloaded

    # Fetch file metadata
    try:
        meta_url = f"{CANVAS_BASE_URL}/api/v1/files/{file_id}"
        r = requests.get(meta_url, cookies=session_cookies, headers=headers, timeout=10)
        if not r.ok:
            return
        f = r.json()

        # Skip video/audio
        ext = Path(f.get("filename", "")).suffix.lower()
        ctype = f.get("content_type", "").lower()
        if ext in SKIP_EXTS or ctype.startswith(("video/", "audio/")):
            return

        # Determine destination — use FILES_CACHE_DIR (never deleted on rebuild)
        import re as _re
        safe_name = _re.sub(r'[<>:"/\\|?*]', "_", f.get("display_name") or f.get("filename", str(file_id)))
        dest_dir = FILES_CACHE_DIR / str(course_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name

        f["local_path"] = str(dest)
        f["course_id"] = course_id
        upsert_file(f, course_id)

        if not dest.exists():
            dl_url = f.get("url", "")
            if dl_url:
                r2 = requests.get(dl_url, cookies=session_cookies, headers=headers,
                                  timeout=30, stream=True)
                if r2.ok:
                    with open(str(dest), "wb") as fp:
                        for chunk in r2.iter_content(8192):
                            fp.write(chunk)
                    console.print(f"  [dim]↓ {safe_name[:50]}[/dim]")

    except Exception as e:
        console.print(f"  [dim]File {file_id}: {e}[/dim]")
