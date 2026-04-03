"""
AI Agent dùng Claude để phân tích và hoàn thành bài tập.
"""
import json
import re
from html.parser import HTMLParser
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from storage.database import get_assignment, get_submission
from config import OPENAI_API_KEY

console = Console()


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


def complete_assignment(assignment_id: int):
    """
    Dùng Claude API để tạo câu trả lời cho assignment.
    Trả về text câu trả lời hoặc None nếu lỗi.
    """
    if not OPENAI_API_KEY:
        console.print("[red]Cần OPENAI_API_KEY trong .env để dùng tính năng này![/red]")
        return None

    assignment = get_assignment(assignment_id)
    if not assignment:
        console.print(f"[red]Không tìm thấy assignment ID {assignment_id}[/red]")
        return None

    submission = get_submission(assignment_id)
    if submission and submission.get("workflow_state") == "submitted":
        console.print("[yellow]Bài này đã được nộp rồi![/yellow]")
        return None

    # Parse thông tin bài
    name = assignment.get("name", "")
    description = strip_html(assignment.get("description", ""))
    points = assignment.get("points_possible", 0)
    due_at = assignment.get("due_at", "")
    submission_types = json.loads(assignment.get("submission_types", "[]"))

    console.print(Panel(f"""[bold]{name}[/bold]
Điểm: {points} | Deadline: {due_at or 'Không có'}
Loại nộp: {', '.join(submission_types)}

[dim]{description[:500]}{'...' if len(description) > 500 else ''}[/dim]""",
        title="Assignment Info", border_style="blue"))

    # Gọi Claude API
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = f"""You are an excellent student at Kent State University.
Complete the following assignment thoroughly, accurately, and academically:

**Assignment:** {name}
**Points:** {points}
**Requirements:**
{description}

Write a complete response in English. The answer should be:
- Thorough and detailed
- Academically formatted
- Cite sources if needed
- Match the assignment requirements exactly
"""

        console.print("[blue]Đang nhờ AI làm bài...[/blue]")
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response.choices[0].message.content
        console.print(Panel(Markdown(answer), title="[bold green]Draft Answer[/bold green]", border_style="green"))
        return answer

    except ImportError:
        console.print("[red]Thiếu thư viện openai. Chạy: pip install openai[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Lỗi khi gọi OpenAI API: {e}[/red]")
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
