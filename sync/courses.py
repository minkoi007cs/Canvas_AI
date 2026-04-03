"""Sync courses từ Canvas API."""
from rich.console import Console
from api.canvas_client import CanvasClient
from storage.database import upsert_course

console = Console()


def sync_courses(client: CanvasClient) -> list[dict]:
    console.print("[blue]Syncing courses...[/blue]")
    courses = client.get("/courses", {"enrollment_state": "active", "include[]": ["term"]})
    for course in courses:
        upsert_course(course)
    console.print(f"  [green]✓ {len(courses)} courses[/green]")
    return courses
