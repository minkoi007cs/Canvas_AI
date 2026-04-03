"""
Tạo folder structure giống Canvas Dashboard:
downloads/
├── _PENDING.md
└── {Course Name}/
    ├── _INDEX.md
    ├── _files/             ← files embedded in pages
    ├── 01 {Module Name}/
    │   ├── 01 {Page Title}.md      ← full text + file links
    │   ├── 02 [TODO] {Assignment}.md
    │   ├── 03 {Quiz}.md
    │   ├── 04 {File}.pdf  (symlink)
    │   └── 05 {Link}.webloc
    └── 02 {Module Name}/
        └── ...
"""
import re
import json
import shutil
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timezone
from rich.console import Console
from storage.database import (
    get_courses, get_modules, get_module_items,
    get_assignments, get_files, get_conn
)
from config import DOWNLOADS_DIR, CANVAS_BASE_URL

console = Console()

VIDEO_DOMAINS = {"youtube.com", "youtu.be", "kaltura", "mediasite",
                 "yuja.com", "panopto.com", "vimeo.com"}


# ─── HTML helpers ─────────────────────────────────────────────────────────────

class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
    def handle_data(self, d):
        self.result.append(d)
    def get_text(self):
        return "\n".join(self.result).strip()


def strip_html(html):
    if not html:
        return ""
    s = HTMLStripper()
    s.feed(html)
    return s.get_text()


def safe(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip(". ")[:80]


# ─── Populate module_items from raw module JSON ────────────────────────────────

def populate_module_items_from_raw():
    """Fill module_items table from raw module JSON already stored in DB."""
    conn = get_conn()
    mod_count = conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
    item_count = conn.execute("SELECT COUNT(*) FROM module_items").fetchone()[0]

    # Re-populate if item count is much less than expected (each module has ~5 items avg)
    if item_count >= mod_count * 2:
        conn.close()
        return  # Already looks populated

    conn.execute("DELETE FROM module_items")
    rows = conn.execute("SELECT id, course_id, raw FROM modules").fetchall()
    total = 0
    for row in rows:
        mod_id = row["id"]
        course_id = row["course_id"]
        data = json.loads(row["raw"])
        for item in data.get("items", []):
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO module_items
                    (id, module_id, course_id, title, type, content_id, url, page_url, raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item["id"],
                    mod_id,
                    course_id,
                    item.get("title", ""),
                    item.get("type", ""),
                    item.get("content_id"),
                    item.get("html_url", ""),
                    item.get("page_url", ""),
                    json.dumps(item),
                ))
                total += 1
            except Exception:
                pass
    conn.commit()
    conn.close()
    console.print(f"  [dim]Loaded {total} module items from cache[/dim]")


# ─── Main build ───────────────────────────────────────────────────────────────

def build_folders():
    """Rebuild toàn bộ folder structure giống Canvas."""
    console.print("[blue]Building folder structure...[/blue]")

    # Ensure module_items populated
    populate_module_items_from_raw()

    courses = get_courses()
    all_pending = []

    for course in courses:
        cid = course["id"]
        cname = safe(course.get("name", str(cid)))
        course_dir = DOWNLOADS_DIR / cname
        course_dir.mkdir(parents=True, exist_ok=True)

        assignments_by_id = {a["id"]: a for a in get_assignments(cid)}
        files_by_id = {f["id"]: f for f in get_files(cid)}
        pages_by_slug = _load_pages(cid)
        course_files_dir = course_dir / "_files"

        # Collect pending
        for a in assignments_by_id.values():
            if not a.get("has_submitted_submissions"):
                all_pending.append({**a, "_course_name": course.get("name", "")})

        modules = get_modules(cid)

        # Write course index
        _write_course_index(course_dir, course, modules, assignments_by_id)

        # Build module folders
        for mod_pos, mod in enumerate(modules, 1):
            mname = safe(mod.get("name", f"Module_{mod['id']}"))
            mod_dir = course_dir / f"{mod_pos:02d} {mname}"
            mod_dir.mkdir(exist_ok=True)

            items = get_module_items(mod["id"])

            # Sort by position
            items_sorted = sorted(items, key=lambda x: json.loads(x["raw"]).get("position", 999))

            item_pos = 0
            for item in items_sorted:
                raw = json.loads(item["raw"])
                item_type = item.get("type", "")
                title = item.get("title", "untitled")
                content_id = item.get("content_id")

                if item_type == "SubHeader":
                    # Visual separator file
                    fname = f"__ {safe(title)} __"
                    (mod_dir / fname).touch()
                    continue

                item_pos += 1
                prefix = f"{item_pos:02d} "

                if item_type == "Page":
                    page_slug = item.get("page_url", "")
                    page = pages_by_slug.get(page_slug)
                    _write_page_item(mod_dir, prefix, title, page, course_files_dir)

                elif item_type == "Assignment" and content_id in assignments_by_id:
                    a = assignments_by_id[content_id]
                    _write_assignment_item(mod_dir, prefix, a)

                elif item_type == "Quiz":
                    canvas_url = raw.get("html_url", "")
                    _write_quiz_item(mod_dir, prefix, title, canvas_url, content_id, assignments_by_id)

                elif item_type == "Discussion":
                    canvas_url = raw.get("html_url", "")
                    _write_link_item(mod_dir, prefix, title, canvas_url, "[Discussion]")

                elif item_type == "File" and content_id in files_by_id:
                    _link_file_item(mod_dir, prefix, files_by_id[content_id])

                elif item_type in ("ExternalUrl", "ExternalTool"):
                    ext_url = raw.get("external_url") or raw.get("html_url", "")
                    _write_webloc(mod_dir, prefix, title, ext_url)

            pending_in_mod = sum(
                1 for it in items_sorted
                if it.get("type") == "Assignment"
                and it.get("content_id") in assignments_by_id
                and not assignments_by_id[it["content_id"]].get("has_submitted_submissions")
            )
            status = f"[yellow]{pending_in_mod} TODO[/yellow]" if pending_in_mod else "[green]✓[/green]"
            console.print(f"    {status} {mname[:40]} ({len(items_sorted)} items)")

        pending_count = sum(1 for a in assignments_by_id.values() if not a.get("has_submitted_submissions"))
        console.print(
            f"  [green]✓ {cname[:50]}[/green]  "
            f"({len(modules)} modules, [yellow]{pending_count} pending[/yellow])"
        )

    _write_pending_summary(all_pending)
    console.print(f"\n[bold green]✓ Done:[/bold green] {DOWNLOADS_DIR}")


# ─── Item writers ─────────────────────────────────────────────────────────────

def _write_page_item(folder, prefix, title, page, course_files_dir=None):
    fname = safe(title) or "page"
    dest = folder / f"{prefix}{fname}.md"
    if dest.exists():
        return

    if not page or not page.get("body"):
        content = f"# {title}\n\n_Content not synced yet. Run `python main.py sync` to fetch._\n"
        dest.write_text(content, encoding="utf-8")
        return

    body_html = page.get("body", "")
    updated = (page.get("updated_at") or "")[:10]

    # Parse body for files and videos
    file_sections, video_section = _parse_page_body(body_html, course_files_dir, folder, prefix)

    # Plain text body
    body_text = _html_to_md(body_html)

    lines = [f"# {title}", f"", f"_Updated: {updated}_", "", "---", ""]

    if file_sections:
        lines.append("## Files")
        lines.extend(file_sections)
        lines.append("")

    if video_section:
        lines.append("## Videos")
        lines.extend(video_section)
        lines.append("")

    lines.append("## Content")
    lines.append("")
    lines.append(body_text)
    lines.append("")

    dest.write_text("\n".join(lines), encoding="utf-8")


def _parse_page_body(html, course_files_dir, mod_folder, prefix):
    """
    Extract file links and video links from page HTML.
    Returns (file_lines, video_lines) for the .md file.
    Symlinks downloaded files into the module folder.
    """
    import re as _re

    file_lines = []
    video_lines = []
    seen_urls = set()

    # Find all hrefs and iframes
    href_pattern = _re.compile(r'href=["\']([^"\']+)["\']', _re.IGNORECASE)
    src_pattern = _re.compile(r'src=["\']([^"\']+)["\']', _re.IGNORECASE)
    title_before = _re.compile(r'>([^<]{1,80})</a>', _re.IGNORECASE)

    all_urls = []
    for m in href_pattern.finditer(html):
        all_urls.append(m.group(1))
    for m in src_pattern.finditer(html):
        all_urls.append(m.group(1))

    for url in all_urls:
        if not url or url in seen_urls:
            continue
        if url.startswith(("javascript:", "mailto:", "#", "data:")):
            continue
        seen_urls.add(url)

        # Video?
        url_lower = url.lower()
        if any(d in url_lower for d in VIDEO_DOMAINS):
            label = url.split("/")[-1].split("?")[0] or "Video"
            video_lines.append(f"- **VIDEO** → [{label}]({url})")
            continue

        # Canvas file?
        fid_match = _re.search(r"/files/(\d+)", url)
        if fid_match:
            fid = int(fid_match.group(1))
            local = _find_local_file(fid)
            if local and Path(local).exists():
                src_path = Path(local)
                link_dest = mod_folder / f"{prefix}{src_path.name}"
                if not link_dest.exists():
                    try:
                        link_dest.symlink_to(src_path.resolve())
                    except Exception:
                        try:
                            shutil.copy2(src_path, link_dest)
                        except Exception:
                            pass
                file_lines.append(f"- [{src_path.name}]({src_path.name})")
            else:
                # File not downloaded yet
                canvas_url = url if url.startswith("http") else f"https://kent.instructure.com{url}"
                file_lines.append(f"- [Canvas File #{fid}]({canvas_url})")
            continue

    return file_lines, video_lines


def _find_local_file(file_id):
    """Look up local_path for a file ID in DB."""
    conn = get_conn()
    row = conn.execute("SELECT local_path FROM files WHERE id=?", (file_id,)).fetchone()
    conn.close()
    return row["local_path"] if row else None


def _html_to_md(html):
    """Convert HTML to readable markdown-ish plain text."""
    if not html:
        return ""
    import re as _re

    # Convert common tags
    text = html
    text = _re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n### \1\n', text, flags=_re.DOTALL|_re.IGNORECASE)
    text = _re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=_re.DOTALL|_re.IGNORECASE)
    text = _re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=_re.DOTALL|_re.IGNORECASE)
    text = _re.sub(r'<em[^>]*>(.*?)</em>', r'_\1_', text, flags=_re.DOTALL|_re.IGNORECASE)
    text = _re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', text, flags=_re.DOTALL|_re.IGNORECASE)
    text = _re.sub(r'<br\s*/?>', '\n', text, flags=_re.IGNORECASE)
    text = _re.sub(r'<p[^>]*>', '\n', text, flags=_re.IGNORECASE)
    text = _re.sub(r'</p>', '\n', text, flags=_re.IGNORECASE)
    text = _re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
                   lambda m: f'[{m.group(2).strip()}]({m.group(1)})' if m.group(2).strip() else m.group(1),
                   text, flags=_re.DOTALL|_re.IGNORECASE)
    # Strip remaining tags
    text = _re.sub(r'<[^>]+>', '', text)
    # Decode entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
               .replace('&nbsp;', ' ').replace('&quot;', '"').replace('&#39;', "'")
    # Clean up whitespace
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _write_assignment_item(folder, prefix, a):
    pending = not a.get("has_submitted_submissions")
    todo = "[TODO] " if pending else ""
    fname = safe(a.get("name", f"assignment_{a['id']}"))
    dest = folder / f"{prefix}{todo}{fname}.md"
    if dest.exists():
        return

    sub_types = json.loads(a.get("submission_types", "[]"))
    due = (a.get("due_at") or "No deadline")[:16].replace("T", " ")
    desc = strip_html(a.get("description", "")) or "_No description_"
    status_badge = "🔴 **NOT SUBMITTED**" if pending else "🟢 Submitted"

    content = f"""# {a.get('name', '')}

> {status_badge}

| | |
|---|---|
| **Points** | {a.get('points_possible', 'N/A')} |
| **Due** | {due} |
| **Type** | {', '.join(sub_types)} |
| **ID** | {a['id']} |

---

{desc}

---

```bash
python main.py complete {a['id']}
```
"""
    dest.write_text(content, encoding="utf-8")


def _write_quiz_item(folder, prefix, title, canvas_url, content_id, assignments_by_id):
    fname = safe(title) or "quiz"
    # Check if quiz is pending from assignments table
    pending = False
    assign_id = None
    if content_id and content_id in assignments_by_id:
        a = assignments_by_id[content_id]
        pending = not a.get("has_submitted_submissions")
        assign_id = a["id"]

    todo = "[TODO] " if pending else ""
    dest = folder / f"{prefix}{todo}{fname}.md"
    if dest.exists():
        return

    quiz_cmd = f"python main.py quiz {assign_id}" if assign_id else "_Not available via CLI_"
    status = "🔴 **NOT SUBMITTED**" if pending else "🟢 Done / N/A"

    content = f"""# {title}

> {status}

| | |
|---|---|
| **Type** | Quiz |
| **Canvas URL** | {canvas_url} |

---

Open in Canvas to take the quiz.

```bash
{quiz_cmd}
```
"""
    dest.write_text(content, encoding="utf-8")


def _write_link_item(folder, prefix, title, url, tag=""):
    fname = safe(title) or "link"
    dest = folder / f"{prefix}{fname}.md"
    if dest.exists():
        return
    content = f"# {title}\n\n{tag}\n\n[Open in Canvas]({url})\n"
    dest.write_text(content, encoding="utf-8")


def _link_file_item(folder, prefix, f):
    local_path = f.get("local_path", "")
    display = safe(f.get("display_name") or f.get("filename", "file"))
    if local_path and Path(local_path).exists():
        src = Path(local_path)
        dest = folder / f"{prefix}{src.name}"
        if dest.exists():
            return
        try:
            dest.symlink_to(src.resolve())
            return
        except Exception:
            try:
                shutil.copy2(src, dest)
                return
            except Exception:
                pass
    # File not downloaded - write a placeholder
    dest = folder / f"{prefix}{display}.md"
    if not dest.exists():
        dest.write_text(f"# {display}\n\n_File not downloaded._\n", encoding="utf-8")


def _write_webloc(folder, prefix, title, url):
    """Write macOS .webloc file (double-click opens in browser)."""
    if not url:
        return
    fname = safe(title) or "link"
    dest = folder / f"{prefix}{fname}.webloc"
    if dest.exists():
        return
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>URL</key>
\t<string>{url}</string>
</dict>
</plist>
"""
    dest.write_text(content, encoding="utf-8")


# ─── Course index ─────────────────────────────────────────────────────────────

def _write_course_index(course_dir, course, modules, assignments_by_id):
    dest = course_dir / "_INDEX.md"
    pending = sum(1 for a in assignments_by_id.values() if not a.get("has_submitted_submissions"))
    lines = [
        f"# {course.get('name', '')}\n",
        f"**{len(modules)} modules** | **{pending} assignments pending**\n",
        "",
        "## Modules\n",
    ]
    for i, m in enumerate(modules, 1):
        lines.append(f"{i:02d}. {m.get('name', '')}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Pending summary ──────────────────────────────────────────────────────────

def _write_pending_summary(pending):
    dest = DOWNLOADS_DIR / "_PENDING.md"

    def sort_key(a):
        return a.get("due_at") or "9999"

    pending_sorted = sorted(pending, key=sort_key)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    lines = [f"# Pending Assignments ({len(pending_sorted)})\n", f"_Updated: {now} UTC_\n", ""]
    current_course = None
    for a in pending_sorted:
        course = a.get("_course_name", "")
        if course != current_course:
            lines.append(f"\n## {course}\n")
            current_course = course
        due = a.get("due_at", "")
        due_str = due[:16].replace("T", " ") if due else "No deadline"
        pts = a.get("points_possible", "?")
        name = a.get("name", "")
        aid = a["id"]
        lines.append(f"- [ ] **{name}** — {due_str} — {pts} pts — `python main.py complete {aid}`")

    dest.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"  [yellow]→ {len(pending_sorted)} pending → _PENDING.md[/yellow]")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_pages(course_id):
    """Load pages indexed by URL slug."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM pages WHERE course_id=?", (course_id,)).fetchall()
    conn.close()
    return {dict(r)["url"]: dict(r) for r in rows}
