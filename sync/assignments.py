"""Sync assignments và submissions từ Canvas API."""
from rich.console import Console
from api.canvas_client import CanvasClient
from storage.database import upsert_assignment, upsert_submission

console = Console()


def sync_assignments(client: CanvasClient, courses: list[dict]):
    console.print("[blue]Syncing assignments...[/blue]")
    total = 0
    for course in courses:
        cid = course["id"]
        cname = course.get("name", str(cid))
        try:
            assignments = client.get(
                f"/courses/{cid}/assignments",
                {"include[]": ["submission", "description"], "order_by": "due_at"},
            )
            for a in assignments:
                a["course_id"] = cid
                upsert_assignment(a)

                # Lưu submission nếu có
                sub = a.get("submission")
                if sub and sub.get("id"):
                    upsert_submission(sub, cid)

            total += len(assignments)
            console.print(f"  [dim]{cname}: {len(assignments)} assignments[/dim]")
        except Exception as e:
            console.print(f"  [red]Lỗi course {cname}: {e}[/red]")

    console.print(f"  [green]✓ {total} assignments tổng cộng[/green]")
