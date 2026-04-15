"""
Data retention and cleanup tasks.
Deletes Canvas data for inactive users after N days.
Handles file cleanup and database record deletion.
"""
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from storage.database import get_conn, set_user_context, clear_user_context
from storage.users import get_users_conn, user_data_dir
from config import get_user_downloads_dir, get_user_files_cache_dir

# Default: delete data if not accessed for 7 days
RETENTION_DAYS = int(os.getenv("CLEANUP_DAYS", "7"))
CLEANUP_ENABLED = os.getenv("CLEANUP_ENABLED", "true").lower() in ("true", "1", "yes")


def get_cutoff_date() -> str:
    """Get ISO timestamp for cutoff (N days ago)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    return cutoff.isoformat()


def cleanup_inactive_users() -> dict:
    """
    Delete all Canvas data for users who haven't synced in RETENTION_DAYS.
    Returns stats: {deleted_users, deleted_records, freed_bytes}
    """
    if not CLEANUP_ENABLED:
        return {"deleted_users": 0, "deleted_records": 0, "freed_bytes": 0}

    stats = {"deleted_users": 0, "deleted_records": 0, "freed_bytes": 0}
    cutoff = get_cutoff_date()

    try:
        # Get all users who haven't been active recently
        # Activity is tracked via last_accessed_at (login, sync, API usage)
        conn = get_users_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT google_id FROM users
            WHERE canvas_linked = 1 AND (
                last_accessed_at IS NULL OR last_accessed_at < %s
            )
        """, (cutoff,))
        inactive_users = [row[0] for row in cur.fetchall()]
        conn.close()

        for google_id in inactive_users:
            deleted = delete_user_canvas_data(google_id)
            stats["deleted_users"] += 1
            stats["deleted_records"] += deleted.get("records", 0)
            stats["freed_bytes"] += deleted.get("bytes", 0)

        return stats

    except Exception as e:
        print(f"[cleanup] Error during inactive user cleanup: {e}", flush=True)
        return stats


def delete_user_canvas_data(google_id: str) -> dict:
    """
    Delete all Canvas data for a specific user.
    Returns {records: count, bytes: size}
    """
    stats = {"records": 0, "bytes": 0}

    try:
        set_user_context(google_id)

        # Delete from database
        conn = get_conn()
        tables = ["submissions", "assignments", "files", "pages", "module_items", "modules", "courses"]
        for table in tables:
            cur = conn.execute(f"DELETE FROM {table} WHERE google_id = %s", (google_id,))
            stats["records"] += cur.rowcount or 0
        conn.commit()
        conn.close()

        # Delete local files
        try:
            data_dir = user_data_dir(google_id)
            if data_dir.exists():
                for f in data_dir.rglob("*"):
                    if f.is_file():
                        stats["bytes"] += f.stat().st_size
                shutil.rmtree(str(data_dir))
        except Exception:
            pass

        clear_user_context()
        return stats

    except Exception as e:
        print(f"[cleanup] Error deleting data for {google_id}: {e}", flush=True)
        clear_user_context()
        return stats


def cleanup_old_files() -> dict:
    """
    Delete local files older than RETENTION_DAYS.
    Returns stats: {files_deleted, bytes_freed}
    """
    stats = {"files_deleted": 0, "bytes_freed": 0}
    cutoff_timestamp = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    try:
        # Get all user data directories
        from config import BASE_DIR
        data_dir = BASE_DIR / "data"
        if not data_dir.exists():
            return stats

        for user_dir in data_dir.iterdir():
            if not user_dir.is_dir():
                continue
            google_id = user_dir.name

            # Delete files in downloads and files_cache
            for subdir_name in ["downloads", "files_cache"]:
                subdir = user_dir / subdir_name
                if not subdir.exists():
                    continue

                for file_path in subdir.rglob("*"):
                    if not file_path.is_file():
                        continue

                    try:
                        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                        if file_mtime < cutoff_timestamp:
                            file_size = file_path.stat().st_size
                            file_path.unlink()
                            stats["files_deleted"] += 1
                            stats["bytes_freed"] += file_size
                    except Exception:
                        pass

        return stats

    except Exception as e:
        print(f"[cleanup] Error during file cleanup: {e}", flush=True)
        return stats


def cleanup_all() -> dict:
    """Run all cleanup tasks. Returns combined stats."""
    stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retention_days": RETENTION_DAYS,
        "enabled": CLEANUP_ENABLED,
    }

    if not CLEANUP_ENABLED:
        print("[cleanup] Cleanup disabled", flush=True)
        return stats

    print(f"[cleanup] Starting cleanup (retention: {RETENTION_DAYS} days)", flush=True)

    # Clean inactive users
    inactive_stats = cleanup_inactive_users()
    stats["inactive_users"] = inactive_stats
    print(f"[cleanup] Deleted {inactive_stats['deleted_users']} inactive users, "
          f"{inactive_stats['deleted_records']} records, "
          f"{inactive_stats['freed_bytes'] / 1024 / 1024:.1f} MB", flush=True)

    # Clean old files
    file_stats = cleanup_old_files()
    stats["old_files"] = file_stats
    print(f"[cleanup] Deleted {file_stats['files_deleted']} old files, "
          f"freed {file_stats['bytes_freed'] / 1024 / 1024:.1f} MB", flush=True)

    print("[cleanup] Cleanup complete", flush=True)
    return stats


if __name__ == "__main__":
    # Can be run as: python -m tasks.cleanup
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    result = cleanup_all()
    import json
    print(json.dumps(result, indent=2))
