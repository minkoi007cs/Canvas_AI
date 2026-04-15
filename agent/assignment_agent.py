"""
AI Agent — làm bài tập với context từ lecture PDFs và readings.

Flow:
  1. Tìm module chứa bài (hỗ trợ cả Assignment lẫn Quiz ID)
  2. Lấy tất cả Page items trong module
  3. Với mỗi page: extract file IDs từ HTML → tìm local PDF → đọc text
  4. Feed context vào GPT-4o → trả lời bài
"""

import json
import re
from pathlib import Path
from html.parser import HTMLParser
from storage.database import get_conn, get_assignment, get_submission, get_current_google_id, load_json
from config import OPENAI_API_KEY

MAX_PDF_CHARS   = 30_000   # per PDF
MAX_TOTAL_CHARS = 100_000  # total context


# ─── HTML helpers ─────────────────────────────────────────────────────────────

class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
    def handle_data(self, d):
        self.result.append(d)
    def get_text(self):
        return " ".join(self.result)

def strip_html(html: str) -> str:
    if not html:
        return ""
    s = HTMLStripper()
    s.feed(html)
    return s.get_text().strip()


def _extract_file_ids(html: str) -> list:
    """Extract Canvas file IDs embedded in page HTML as /files/12345 links."""
    ids = re.findall(r'/files/(\d+)', html or "")
    seen, out = set(), []
    for fid in ids:
        if fid not in seen:
            seen.add(fid)
            out.append(int(fid))
    return out


# ─── PDF extraction ────────────────────────────────────────────────────────────

def _read_pdf(path: str, max_chars: int = MAX_PDF_CHARS) -> str:
    """Extract text from a local PDF file. Returns empty string on failure."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        parts = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            if total + len(text) > max_chars:
                parts.append(text[: max_chars - total])
                break
            parts.append(text)
            total += len(text)
        raw = " ".join(parts)
        # Clean up whitespace artifacts common in PDFs
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw
    except Exception:
        return ""


# ─── Context gathering ─────────────────────────────────────────────────────────

def gather_module_context(assignment_id: int) -> dict:
    """
    Returns:
        {
          module_name: str,
          course_id: int,
          course_name: str,
          sources: [{"title": str, "text": str, "type": "page"|"pdf"}, ...],
          context_text: str,
        }
    """
    gid = get_current_google_id()
    conn = get_conn()

    # ── 1. Find module_id ────────────────────────────────────────────────────
    # Assignments map directly (type=Assignment)
    row = conn.execute("""
        SELECT mi.module_id, mi.course_id, m.name as module_name
        FROM module_items mi JOIN modules m ON m.id = mi.module_id AND m.google_id = mi.google_id
        WHERE mi.google_id = ? AND mi.content_id = ? AND mi.type = 'Assignment'
        LIMIT 1
    """, (gid, assignment_id,)).fetchone()

    # Quizzes: module_items.content_id = quiz_id (not assignment id)
    if not row:
        a = conn.execute(
            "SELECT raw FROM assignments WHERE google_id = ? AND id = ?", (gid, assignment_id,)
        ).fetchone()
        if a:
            quiz_id = load_json(a["raw"]).get("quiz_id")
            if quiz_id:
                row = conn.execute("""
                    SELECT mi.module_id, mi.course_id, m.name as module_name
                    FROM module_items mi JOIN modules m ON m.id = mi.module_id AND m.google_id = mi.google_id
                    WHERE mi.google_id = ? AND mi.content_id = ? AND mi.type = 'Quiz'
                    LIMIT 1
                """, (gid, quiz_id,)).fetchone()

    if not row:
        conn.close()
        return {"module_name": None, "course_id": None, "course_name": None, "sources": [], "context_text": ""}

    module_id   = row["module_id"]
    course_id   = row["course_id"]
    module_name = row["module_name"]

    # Get course name
    course_row = conn.execute(
        "SELECT name FROM courses WHERE google_id = ? AND id = ?", (gid, course_id,)
    ).fetchone()
    course_name = course_row["name"] if course_row else "Unknown Course"

    # ── 2. Get all Page items in this module ─────────────────────────────────
    page_items = conn.execute("""
        SELECT mi.title, mi.page_url
        FROM module_items mi
        WHERE mi.google_id = ? AND mi.module_id = ? AND mi.type = 'Page' AND mi.page_url != ''
        ORDER BY mi.id
    """, (gid, module_id,)).fetchall()

    # ── 3. Build file_id → local_path lookup for this course ─────────────────
    file_rows = conn.execute(
        "SELECT id, display_name, local_path FROM files WHERE google_id = ? AND course_id = ?",
        (gid, course_id,)
    ).fetchall()
    file_map = {r["id"]: r for r in file_rows}

    sources = []
    total_chars = 0

    for item in page_items:
        slug = item["page_url"]
        page = conn.execute("""
            SELECT title, body FROM pages
            WHERE google_id = ? AND url = ? AND course_id = ?
        """, (gid, slug, course_id)).fetchone()

        if not page or not page["body"]:
            continue

        page_title = page["title"] or item["title"]

        # ── 3a. Extract page overview text ───────────────────────────────────
        overview = strip_html(page["body"])
        if overview and len(overview) > 80:
            chunk = overview[:3000]
            sources.append({"title": page_title, "text": chunk, "type": "page"})
            total_chars += len(chunk)

        # ── 3b. Extract linked PDFs from page HTML ───────────────────────────
        if total_chars >= MAX_TOTAL_CHARS:
            break

        file_ids = _extract_file_ids(page["body"])
        for fid in file_ids:
            if total_chars >= MAX_TOTAL_CHARS:
                break
            frow = file_map.get(fid)
            if not frow or not frow["local_path"]:
                continue
            lpath = frow["local_path"]
            if not Path(lpath).exists():
                continue
            suffix = Path(lpath).suffix.lower()
            if suffix not in (".pdf", ".txt"):
                continue

            fname = frow["display_name"] or Path(lpath).name

            # Skip duplicate files already added (same display_name)
            if any(s["title"] == fname for s in sources):
                continue

            if suffix == ".pdf":
                text = _read_pdf(lpath)
            else:
                try:
                    text = Path(lpath).read_text(errors="replace")[:MAX_PDF_CHARS]
                except Exception:
                    text = ""

            if len(text) < 100:
                continue

            text = text[:MAX_PDF_CHARS]
            sources.append({"title": fname, "text": text, "type": "pdf"})
            total_chars += len(text)

    conn.close()

    # ── 4. Combine context string ─────────────────────────────────────────────
    parts = []
    running = 0
    for s in sources:
        block = f"=== {s['title']} ===\n{s['text']}\n"
        if running + len(block) > MAX_TOTAL_CHARS:
            break
        parts.append(block)
        running += len(block)

    return {
        "module_name": module_name,
        "course_id": course_id,
        "course_name": course_name,
        "sources": sources,
        "context_text": "\n".join(parts),
    }


# ─── Main AI completion ────────────────────────────────────────────────────────

def complete_assignment_from_context(assignment_title: str,
                                     assignment_description: str,
                                     context_text: str = "",
                                     course_name: str = "Unknown Course",
                                     progress_cb=None) -> str:
    """
    Generate assignment response from provided context (for extension API).

    Does NOT perform database lookups. All data comes from parameters.

    Args:
        assignment_title: Assignment name
        assignment_description: Assignment instructions/prompt
        context_text: Relevant course materials (PDFs, notes, readings)
        course_name: Course name for system prompt
        progress_cb: Callback for progress updates

    Returns:
        AI-generated draft response or error message
    """
    from config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        if progress_cb:
            progress_cb("Cần ANTHROPIC_API_KEY trong .env")
        return "ERROR: ANTHROPIC_API_KEY not configured"

    def emit(msg):
        if progress_cb:
            progress_cb(msg)

    emit("Phân tích tài liệu...")

    # Truncate context if too large
    if len(context_text) > MAX_TOTAL_CHARS:
        context_text = context_text[:MAX_TOTAL_CHARS]
        emit(f"Context truncated to {MAX_TOTAL_CHARS:,} characters")

    # Build system prompt
    system_prompt = (
        f"You are an excellent student at Kent State University taking {course_name}. "
        "You write thorough, well-organized, academically strong responses. "
        "When course materials are provided below, base your answers DIRECTLY on them — "
        "cite specific details, examples, and quotes from those materials. "
        "Write in clear academic English unless otherwise specified."
    )

    # Build context section
    context_section = ""
    if context_text:
        context_section = f"""
---
## Course Materials

The following are lecture transcripts, study guides, and readings relevant to this assignment.
Use them as your PRIMARY source. Reference specific content from these materials.

{context_text}
---
"""

    # Build user prompt
    user_prompt = f"""## Assignment: {assignment_title}

{assignment_description}
{context_section}
## Your Response

Write a complete, thoughtful response to this assignment:"""

    emit("Tạo câu trả lời...")

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        answer = response.content[0].text
        emit("Hoàn thành!")
        return answer

    except Exception as e:
        emit(f"Lỗi Claude: {e}")
        return f"ERROR: {str(e)}"


def complete_assignment(assignment_id: int, progress_cb=None):
    """
    Generate an answer for an assignment using Claude AI.
    Reads course materials from module context, generates thoughtful responses.
    progress_cb(msg: str) is called for live status updates.
    Returns: str or None
    """
    from config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        if progress_cb:
            progress_cb("Cần ANTHROPIC_API_KEY trong .env")
        return None

    def emit(msg):
        if progress_cb:
            progress_cb(msg)

    assignment = get_assignment(assignment_id)
    if not assignment:
        return None

    name        = assignment.get("name", "")
    description = strip_html(assignment.get("description", ""))
    points      = assignment.get("points_possible", 0)
    sub_types   = load_json(assignment.get("submission_types", "[]"))

    # ── Step 1: gather context ────────────────────────────────────────────────
    emit("Đang tìm tài liệu liên quan trong module...")
    ctx = gather_module_context(assignment_id)
    module_name  = ctx.get("module_name") or ""
    course_name  = ctx.get("course_name") or "Unknown Course"
    context_text = ctx.get("context_text") or ""
    sources      = ctx.get("sources") or []

    pdf_sources  = [s for s in sources if s["type"] == "pdf"]
    page_sources = [s for s in sources if s["type"] == "page"]

    if pdf_sources:
        emit(f"Đọc {len(pdf_sources)} file PDF: {', '.join(s['title'][:30] for s in pdf_sources[:3])}{'...' if len(pdf_sources)>3 else ''}")
    if page_sources:
        emit(f"Đọc {len(page_sources)} trang: {', '.join(s['title'][:25] for s in page_sources[:3])}")
    if not sources:
        emit("Không tìm thấy tài liệu — dùng kiến thức chung")

    emit(f"Context: {len(context_text):,} ký tự từ {len(sources)} tài liệu")

    # ── Step 2: build prompt ──────────────────────────────────────────────────
    emit("Đang phân tích đề bài...")

    system_prompt = (
        f"You are an excellent student at Kent State University taking {course_name}. "
        "You write thorough, well-organized, academically strong responses. "
        "When course materials are provided below, base your answers DIRECTLY on them — "
        "cite specific details, examples, and quotes from those materials. "
        "Write in clear academic English unless otherwise specified."
    )

    context_section = ""
    if context_text:
        context_section = f"""
---
## Course Materials (Module: {module_name})

The following are lecture transcripts, study guides, and readings from this module.
Use them as your PRIMARY source. Reference specific content from these materials.

{context_text}
---
"""

    # Detect assignment type to tailor instructions
    is_essay    = "online_text_entry" in sub_types or "online_upload" in sub_types
    is_quiz     = "online_quiz" in sub_types
    is_discuss  = "discussion_topic" in sub_types

    if is_essay:
        format_instructions = """
Write a complete academic essay response:
- If the assignment specifies a length/word count, match it exactly
- Include an introduction with thesis, body paragraphs with evidence, and conclusion
- Reference specific details from the course materials provided
- Use your own words except for direct quotes (which must be in quotation marks)
- Format as plain text (no markdown headers) unless the assignment specifies otherwise
"""
    elif is_discuss:
        format_instructions = """
Write a thoughtful discussion post:
- Engage directly with the question/prompt
- Reference specific examples from course materials
- Write in first person, academic but conversational tone
- 200-400 words unless otherwise specified
"""
    else:
        format_instructions = """
Answer each question or prompt thoroughly with specific evidence from course materials.
"""

    user_prompt = f"""## Assignment: {name}
**Module:** {module_name or "Unknown"}
**Points:** {points}

## Instructions / Prompt
{description or "(No description available)"}
{context_section}
## Response Format
{format_instructions}

Write your complete response now:"""

    # ── Step 3: call AI ───────────────────────────────────────────────────────
    emit("Đang tạo câu trả lời với Claude...")

    try:
        from anthropic import Anthropic
        from config import ANTHROPIC_API_KEY
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        answer = response.content[0].text
        emit("Hoàn thành!")
        return answer

    except Exception as e:
        emit(f"Lỗi Claude: {e}")
        return None


def review_and_edit(draft: str) -> str:
    """CLI: review and optionally edit draft before submit."""
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    console = Console()
    console.print(Panel(Markdown(draft), title="[bold green]Draft[/bold green]", border_style="green"))
    console.print("[dim]Nhập 'ok' để chấp nhận, 'edit' để sửa, 'cancel' để hủy[/dim]")
    choice = console.input("[bold]Lựa chọn (ok/edit/cancel): [/bold]").strip().lower()
    if choice == "cancel":
        return None
    if choice == "edit":
        lines = []
        console.print("[dim]Nhập câu trả lời mới, kết thúc bằng '---END---':[/dim]")
        while True:
            line = input()
            if line == "---END---":
                break
            lines.append(line)
        return "\n".join(lines)
    return draft
