"""Sync modules, module items và pages từ Canvas API."""
from rich.console import Console
from api.canvas_client import CanvasClient
from storage.database import upsert_module, upsert_module_item, upsert_page

console = Console()


def sync_modules(client: CanvasClient, courses: list):
    console.print("[blue]Syncing modules & pages...[/blue]")
    for course in courses:
        cid = course["id"]
        cname = course.get("name", str(cid))
        try:
            modules = client.get(f"/courses/{cid}/modules", {"include[]": ["items", "content_details"]})
            for m in modules:
                upsert_module(m, cid)
                for item in m.get("items", []):
                    upsert_module_item(item, m["id"], cid)
            console.print(f"  [dim]{cname}: {len(modules)} modules[/dim]")
        except Exception as e:
            console.print(f"  [red]Lỗi modules {cname}: {e}[/red]")

        try:
            pages = client.get(f"/courses/{cid}/pages", {"include[]": ["body"]})
            for p in pages:
                upsert_page(p, cid)
        except Exception:
            pass  # Một số course không có pages

    console.print("[green]✓ Modules & pages sync xong[/green]")
