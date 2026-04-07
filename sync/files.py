"""Download files từ Canvas về local."""
import re
from pathlib import Path
from rich.console import Console
from rich.progress import Progress
from api.canvas_client import CanvasClient
from storage.database import upsert_file
from config import DOWNLOADS_DIR, FILES_CACHE_DIR

console = Console()

# Bỏ qua các định dạng video/audio nặng
SKIP_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".mp3", ".wav", ".m4a", ".aac",
    ".m4v", ".mpeg", ".mpg",
}
SKIP_CONTENT_TYPES = {
    "video/", "audio/",
}


def _is_video(f: dict) -> bool:
    name = (f.get("display_name") or f.get("filename", "")).lower()
    ext = Path(name).suffix
    if ext in SKIP_EXTENSIONS:
        return True
    ctype = f.get("content_type", "").lower()
    return any(ctype.startswith(t) for t in SKIP_CONTENT_TYPES)


def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def sync_files(client: CanvasClient, courses: list, download: bool = True):
    from config import get_user_downloads_dir, get_user_files_cache_dir
    downloads_dir  = get_user_downloads_dir()
    files_cache_dir = get_user_files_cache_dir()

    console.print("[blue]Syncing files...[/blue]")
    for course in courses:
        cid = course["id"]
        cname = _safe_name(course.get("name", str(cid)))
        course_dir = downloads_dir / cname
        course_dir.mkdir(parents=True, exist_ok=True)

        try:
            files = client.get(f"/courses/{cid}/files")
            console.print(f"  [dim]{course['name']}: {len(files)} files[/dim]")

            kept = [f for f in files if not _is_video(f)]
            skipped = len(files) - len(kept)
            if skipped:
                console.print(f"  [dim]Bỏ qua {skipped} video/audio[/dim]")

            files_dir = files_cache_dir / str(cid)
            files_dir.mkdir(parents=True, exist_ok=True)

            with Progress() as progress:
                task = progress.add_task(f"  Downloading {cname}...", total=len(kept))
                for f in kept:
                    fname = _safe_name(f.get("display_name") or f.get("filename", str(f["id"])))
                    local_path = files_dir / fname
                    f["local_path"] = str(local_path)
                    upsert_file(f, cid)

                    if download and not local_path.exists():
                        dl_url = f.get("url")
                        if dl_url:
                            client.download_file(dl_url, local_path)
                    progress.advance(task)

        except Exception as e:
            console.print(f"  [red]Lỗi files course {course.get('name')}: {e}[/red]")

    console.print("[green]✓ Files sync xong[/green]")
