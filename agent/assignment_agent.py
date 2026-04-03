"""
AI Agent dùng GPT-4o để phân tích và hoàn thành bài tập.
Context được tự động lấy từ các lecture/readings trong cùng module.
"""
import json
import re
from html.parser import HTMLParser
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from storage.database import get_conn, get_assignment, get_submission
from config import OPENAI_API_KEY

console = Console()

MAX_CONTEXT_CHARS = 40_000   # limit per page body to avoid token overflow
MAX_TOTAL_CONTEXT  = 80_000  # total context fed to AI


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


# ─── Context gathering ─────────────────────────────────────────────────────────

def gather_module_context(assignment_id: int) -> dict:
    """
    Tìm module chứa bài tập này → lấy tất cả lecture / reading pages
    trong cùng module → trả về context text và metadata.

    Returns:
        {
          "module_name": str,
          "course_id": int,
          "pages": [{"title": str, "url": str, "text": str}, ...],
          "context_text": str,   # combined text for AI
          "sources": [str],      # list of page titles used
        }
    """
    conn = get_conn()

    # 1. Find which module(s) contain this assignment/quiz
    rows = conn.execute("""
        SELECT mi.module_id, mi.course_id, m.name as module_name
        FROM module_items mi
        JOIN modules m ON m.id = mi.module_id
        WHERE mi.content_id = ? AND mi.type IN ('Assignment','Quiz','Discussion')
        LIMIT 3
    """, (assignment_id,)).fetchall()

    if not rows:
        conn.close()
        return {"module_name": None, "course_id": None, "pages": [], "context_text": "", "sources": []}

    result_pages = []
    all_sources = []
    module_name = rows[0]["module_name"]
    course_id = rows[0]["course_id"]

    for row in rows:
        module_id = row["module_id"]
        mod_course_id = row["course_id"]

        # 2. Get all Page items in this module
        page_items = conn.execute("""
            SELECT mi.title, mi.page_url
            FROM module_items mi
            WHERE mi.module_id = ? AND mi.type = 'Page' AND mi.page_url != ''
            ORDER BY mi.id
        """, (module_id,)).fetchall()

        for item in page_items:
            slug = item["page_url"]
            page = conn.execute("""
                SELECT title, body, url FROM pages
                WHERE url = ? AND course_id = ? AND body IS NOT NULL AND body != ''
            """, (slug, mod_course_id)).fetchone()

            if not page:
                continue

            text = strip_html(page["body"])
            if len(text) < 50:
                continue

            # Trim overly long pages
            if len(text) > MAX_CONTEXT_CHARS:
                text = text[:MAX_CONTEXT_CHARS] + "...[truncated]"

            result_pages.append({
                "title": page["title"] or item["title"],
                "url": slug,
                "text": text,
            })
            all_sources.append(page["title"] or item["title"])

    conn.close()

    # 3. Combine into one context string, with section headers
    parts = []
    total = 0
    for p in result_pages:
        block = f"=== {p['title']} ===\n{p['text']}\n"
        if total + len(block) > MAX_TOTAL_CONTEXT:
            break
        parts.append(block)
        total += len(block)

    context_text = "\n".join(parts)

    return {
        "module_name": module_name,
        "course_id": course_id,
        "pages": result_pages,
        "context_text": context_text,
        "sources": all_sources,
    }


# ─── Main AI completion ────────────────────────────────────────────────────────

def complete_assignment(assignment_id: int, progress_cb=None):
    """
    Dùng GPT-4o để tạo câu trả lời cho assignment.
    Tự động thu thập lecture/reading context từ cùng module.

    progress_cb: optional callback(step: str) for real-time UI updates
    Returns: str (answer) or None
    """
    if not OPENAI_API_KEY:
        return None

    def emit(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            console.print(f"[dim]{msg}[/dim]")

    assignment = get_assignment(assignment_id)
    if not assignment:
        return None

    name        = assignment.get("name", "")
    description = strip_html(assignment.get("description", ""))
    points      = assignment.get("points_possible", 0)
    raw         = json.loads(assignment.get("raw", "{}"))
    course_id   = assignment.get("course_id")

    # ── Step 1: gather context ───────────────────────────────────────────────
    emit("Đang tìm lectures và readings liên quan...")
    ctx = gather_module_context(assignment_id)
    sources = ctx["sources"]
    context_text = ctx["context_text"]
    module_name = ctx["module_name"] or "Unknown Module"

    if sources:
        emit(f"Tìm thấy {len(sources)} tài liệu: {', '.join(sources[:3])}{'...' if len(sources)>3 else ''}")
    else:
        emit("Không tìm thấy tài liệu liên quan — dùng kiến thức chung")

    # ── Step 2: build prompt ─────────────────────────────────────────────────
    emit("Đang phân tích bài tập...")

    system_prompt = (
        "You are an excellent student at Kent State University. "
        "You write well-organized, academically strong responses. "
        "When course materials are provided, base your answer on them directly — "
        "use specific examples, references, and details from those materials. "
        "Write in clear academic English unless the assignment specifies otherwise."
    )

    context_section = ""
    if context_text:
        context_section = f"""
## Course Materials (from module: {module_name})

The following lecture notes and readings are from the same module as this assignment.
Use these as your primary source. Reference specific details where relevant.

---
{context_text}
---
"""

    user_prompt = f"""
## Assignment: {name}
**Module:** {module_name}
**Points:** {points}

## Assignment Description / Instructions
{description or "(No description provided)"}
{context_section}
## Your Task
Write a complete, high-quality response to this assignment.
- If it asks for an essay: write a full essay with intro, body paragraphs, and conclusion
- If it asks specific questions: answer each question clearly and thoroughly
- If it asks for analysis: provide detailed analysis with evidence from the course materials above
- Use specific quotes or examples from the course materials when relevant
- Match the format the assignment requests (essay, short answer, etc.)
- Aim for the quality of an A-grade student response

Write your response now:
"""

    # ── Step 3: call AI ──────────────────────────────────────────────────────
    emit("Đang tạo câu trả lời với AI...")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        answer = response.choices[0].message.content
        emit("Hoàn thành!")
        return answer

    except Exception as e:
        emit(f"Lỗi: {e}")
        return None


def review_and_edit(draft: str) -> str:
    """Cho user review và chỉnh sửa draft trước khi submit."""
    console.print("\n[bold yellow]Review câu trả lời trước khi submit:[/bold yellow]")
    console.print("[dim]Nhập 'ok' để chấp nhận, 'edit' để sửa, 'cancel' để hủy[/dim]")

    choice = console.input("[bold]Lựa chọn (ok/edit/cancel): [/bold]").strip().lower()

    if choice == "cancel":
        return None
    elif choice == "edit":
        console.print("[dim]Nhập câu trả lời mới (kết thúc bằng dòng '---END---'):[/dim]")
        lines = []
        while True:
            line = input()
            if line == "---END---":
                break
            lines.append(line)
        return "\n".join(lines)
    else:
        return draft
