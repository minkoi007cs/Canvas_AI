#!/usr/bin/env python3
"""
Canvas App - CLI entry point
Kent State University Canvas Automation Tool

Usage:
    python main.py sync                              # Sync toàn bộ từ Canvas
    python main.py list courses                      # Xem danh sách courses
    python main.py list assignments                  # Xem tất cả assignments
    python main.py list assignments --course 12345   # Assignments của 1 course
    python main.py show assignment 67890             # Chi tiết 1 assignment
    python main.py complete 67890                    # AI làm bài, review rồi submit
"""
import sys
import json
import argparse
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from config import DOWNLOADS_DIR
from html.parser import HTMLParser

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


def cmd_sync(args):
    """Sync toàn bộ dữ liệu từ Canvas."""
    from auth.browser_auth import login, load_saved_cookies
    from api.canvas_client import CanvasClient
    from storage.database import init_db
    from sync.courses import sync_courses
    from sync.assignments import sync_assignments
    from sync.files import sync_files
    from sync.modules import sync_modules
    from sync.organizer import build_folders

    init_db()

    # Thử load cookies cũ trước
    cookies = None
    if not args.relogin:
        cookies = load_saved_cookies()
        if cookies:
            console.print("[dim]Dùng session đã lưu...[/dim]")

    from auth.browser_auth import load_saved_token
    api_token = load_saved_token()

    if not cookies:
        from config import CANVAS_USERNAME, CANVAS_PASSWORD
        username = args.username or CANVAS_USERNAME
        password = args.password or CANVAS_PASSWORD

        if not username:
            username = console.input("[bold]FlashLine ID: [/bold]").strip()
        if not password:
            import getpass
            password = getpass.getpass("Password: ")

        cookies, api_token = login(username, password, headless=args.headless)
        if not cookies:
            console.print("[red]Đăng nhập thất bại![/red]")
            return

    client = CanvasClient(cookies=cookies, api_token=api_token)

    console.print("\n[bold]Bắt đầu sync...[/bold]")
    courses = sync_courses(client)

    if not courses:
        console.print("[red]Không lấy được courses. Thử login lại với --relogin[/red]")
        return

    sync_assignments(client, courses)

    if not args.no_files:
        sync_files(client, courses, download=True)

    sync_modules(client, courses)

    # Fetch page bodies + download embedded files
    console.print("\n[bold]Đang tải nội dung trang...[/bold]")
    from sync.pages_deep import sync_pages_deep
    _cookies = load_saved_cookies()
    sync_pages_deep(_cookies)

    console.print("\n[bold]Tạo folder structure...[/bold]")
    build_folders()

    console.print("\n[bold green]✓ Sync hoàn tất![/bold green]")
    console.print(f"[dim]Xem folders tại: {DOWNLOADS_DIR}[/dim]")


def cmd_list(args):
    """Hiển thị danh sách courses hoặc assignments."""
    from storage.database import get_courses, get_assignments

    if args.what == "courses":
        courses = get_courses()
        if not courses:
            console.print("[yellow]Chưa có dữ liệu. Chạy: python main.py sync[/yellow]")
            return

        table = Table(title=f"Courses ({len(courses)})", show_lines=True)
        table.add_column("ID", style="dim", width=10)
        table.add_column("Tên Course", style="bold")
        table.add_column("Code", width=15)
        table.add_column("Status", width=12)

        for c in courses:
            table.add_row(
                str(c["id"]),
                c.get("name", ""),
                c.get("course_code", ""),
                c.get("workflow_state", ""),
            )
        console.print(table)

    elif args.what == "assignments":
        course_id = getattr(args, "course", None)
        assignments = get_assignments(course_id)
        if not assignments:
            console.print("[yellow]Không có assignments. Chạy: python main.py sync[/yellow]")
            return

        table = Table(title=f"Assignments ({len(assignments)})", show_lines=True)
        table.add_column("ID", style="dim", width=10)
        table.add_column("Tên", style="bold")
        table.add_column("Điểm", width=8)
        table.add_column("Deadline", width=22)
        table.add_column("Đã nộp", width=10)
        table.add_column("Course ID", width=12)

        for a in assignments:
            submitted = "[green]✓[/green]" if a.get("has_submitted_submissions") else "[red]✗[/red]"
            due = a.get("due_at", "")
            if due:
                due = due[:16].replace("T", " ")
            table.add_row(
                str(a["id"]),
                a.get("name", ""),
                str(a.get("points_possible", "")),
                due,
                submitted,
                str(a.get("course_id", "")),
            )
        console.print(table)


def cmd_show(args):
    """Xem chi tiết một assignment."""
    from storage.database import get_assignment, get_submission

    assignment = get_assignment(args.id)
    if not assignment:
        console.print(f"[red]Không tìm thấy assignment ID {args.id}[/red]")
        return

    desc = strip_html(assignment.get("description", ""))
    sub_types = json.loads(assignment.get("submission_types", "[]"))

    console.print(Panel(
        f"""[bold]{assignment['name']}[/bold]

[bold]Course ID:[/bold] {assignment['course_id']}
[bold]Điểm:[/bold] {assignment.get('points_possible', 'N/A')}
[bold]Deadline:[/bold] {assignment.get('due_at', 'Không có')}
[bold]Loại nộp:[/bold] {', '.join(sub_types)}
[bold]Trạng thái:[/bold] {assignment.get('workflow_state', '')}

[bold]Mô tả:[/bold]
{desc or '[dim]Không có mô tả[/dim]'}""",
        title=f"[bold]Assignment #{args.id}[/bold]",
        border_style="blue",
    ))

    submission = get_submission(args.id)
    if submission:
        state_color = "green" if submission.get("workflow_state") == "graded" else "yellow"
        console.print(Panel(
            f"""[bold]Trạng thái:[/bold] [{state_color}]{submission.get('workflow_state', '')}[/{state_color}]
[bold]Điểm nhận:[/bold] {submission.get('score', 'Chưa có')}
[bold]Grade:[/bold] {submission.get('grade', 'Chưa có')}
[bold]Nộp lúc:[/bold] {submission.get('submitted_at', 'Chưa nộp')}""",
            title="Submission",
            border_style="green",
        ))


def cmd_quiz(args):
    """Mở quiz bằng browser, AI đọc câu hỏi và đưa đáp án."""
    from storage.database import get_assignment
    from auth.browser_auth import load_saved_cookies
    from agent.quiz_agent import solve_quiz
    import json

    assignment = get_assignment(args.id)
    if not assignment:
        console.print(f"[red]Không tìm thấy assignment ID {args.id}[/red]")
        return

    raw = json.loads(assignment["raw"])
    quiz_id = raw.get("quiz_id")
    if not quiz_id:
        console.print("[red]Bài này không phải quiz[/red]")
        return

    cookies = load_saved_cookies()
    if not cookies:
        console.print("[red]Chưa có session. Chạy sync trước.[/red]")
        return

    console.print(Panel(
        f"[bold]{assignment['name']}[/bold]\n"
        f"Điểm: {assignment.get('points_possible')} | Quiz ID: {quiz_id}\n\n"
        f"[dim]Browser sẽ mở, AI đọc câu hỏi rồi đưa đáp án.[/dim]",
        border_style="blue",
    ))

    solve_quiz(
        course_id=assignment["course_id"],
        quiz_id=quiz_id,
        assignment_id=args.id,
        cookies=cookies,
        headless=False,
    )


def _cmd_get_token():
    """Login lại để lấy API token từ Canvas profile."""
    from auth.browser_auth import login, load_saved_token
    from config import CANVAS_USERNAME, CANVAS_PASSWORD

    existing = load_saved_token()
    if existing:
        console.print(f"[green]✓ Đã có API token[/green]")
        return

    console.print("[blue]Đang login để lấy API token...[/blue]")
    cookies, api_token = login(CANVAS_USERNAME, CANVAS_PASSWORD, headless=False)
    if api_token:
        console.print("[bold green]✓ Lấy API token thành công! Giờ có thể submit bài.[/bold green]")
    else:
        console.print("[yellow]Không lấy được token tự động.[/yellow]")
        console.print("Vào Canvas > Account > Settings > New Access Token")
        console.print("Rồi lưu token vào .env: CANVAS_API_TOKEN=your_token")


SUBMITTABLE_TYPES = {"online_text_entry", "online_upload", "online_url"}

QUIZ_TYPES = {"online_quiz"}

UNSUBMITTABLE_TYPES = {"none", "not_graded", "on_paper", "external_tool", "discussion_topic"}


def _get_client():
    from auth.browser_auth import load_saved_cookies, load_saved_token
    from api.canvas_client import CanvasClient
    import os
    cookies = load_saved_cookies()
    # Ưu tiên: env var > file token > cookies
    api_token = os.getenv("CANVAS_API_TOKEN", "") or load_saved_token()
    if not cookies and not api_token:
        console.print("[red]Chưa có session. Chạy: python main.py sync[/red]")
        return None
    return CanvasClient(cookies=cookies, api_token=api_token)


def cmd_complete(args):
    """Dùng AI tạo câu trả lời, review, rồi submit."""
    from agent.assignment_agent import complete_assignment, review_and_edit
    from storage.database import get_assignment

    assignment = get_assignment(args.id)
    if not assignment:
        console.print(f"[red]Không tìm thấy assignment ID {args.id}[/red]")
        return

    sub_types = set(json.loads(assignment.get("submission_types", "[]")))
    name = assignment.get("name", "")

    # Quiz → không hỗ trợ submit qua API
    if sub_types & QUIZ_TYPES:
        console.print(Panel(
            f"[bold yellow]⚠ Bài này là QUIZ[/bold yellow]\n\n"
            f"[bold]{name}[/bold]\n\n"
            f"Quiz phải làm trực tiếp trên Canvas, không thể submit qua API.\n\n"
            f"[dim]Mở Canvas:[/dim] https://kent.instructure.com/courses/{assignment['course_id']}/assignments/{args.id}",
            border_style="yellow",
        ))
        return

    # Không có loại nộp online
    if sub_types & UNSUBMITTABLE_TYPES or not (sub_types & SUBMITTABLE_TYPES):
        console.print(Panel(
            f"[yellow]Loại nộp:[/yellow] {', '.join(sub_types)}\n\n"
            f"Bài này không hỗ trợ nộp qua API (nộp tay trên giấy, hoặc external tool).\n\n"
            f"[dim]Link Canvas:[/dim] https://kent.instructure.com/courses/{assignment['course_id']}/assignments/{args.id}",
            border_style="yellow",
        ))
        return

    # Xác định submission_type ưu tiên
    if "online_text_entry" in sub_types:
        submit_type = "online_text_entry"
    elif "online_upload" in sub_types:
        submit_type = "online_upload"
    else:
        submit_type = list(sub_types & SUBMITTABLE_TYPES)[0]

    # AI tạo draft
    draft = complete_assignment(args.id)
    if not draft:
        return

    # Review
    final = review_and_edit(draft)
    if not final:
        console.print("[yellow]Đã hủy submit.[/yellow]")
        return

    # Submit
    console.print("\n[blue]Đang submit bài...[/blue]")
    client = _get_client()
    if not client:
        return

    try:
        course_id = assignment["course_id"]
        result = client.post(
            f"/courses/{course_id}/assignments/{args.id}/submissions",
            {"submission": {"submission_type": submit_type, "body": final}},
        )
        console.print("[bold green]✓ Nộp bài thành công![/bold green]")
        console.print(f"[dim]Submission ID: {result.get('id')}[/dim]")
    except Exception as e:
        console.print(f"[red]Lỗi khi submit: {e}[/red]")
        console.print(f"[dim]Thử mở Canvas thủ công: https://kent.instructure.com/courses/{assignment['course_id']}/assignments/{args.id}[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Canvas App - Kent State University",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    # sync
    p_sync = sub.add_parser("sync", help="Sync dữ liệu từ Canvas")
    p_sync.add_argument("--username", "-u", help="FlashLine ID")
    p_sync.add_argument("--password", "-p", help="Password")
    p_sync.add_argument("--relogin", action="store_true", help="Bỏ session cũ, login lại")
    p_sync.add_argument("--headless", action="store_true", help="Chạy browser ẩn (không hiện cửa sổ)")
    p_sync.add_argument("--no-files", action="store_true", help="Bỏ qua download files")

    # list
    p_list = sub.add_parser("list", help="Xem danh sách")
    p_list.add_argument("what", choices=["courses", "assignments"])
    p_list.add_argument("--course", type=int, help="Lọc theo course ID")

    # show
    p_show = sub.add_parser("show", help="Xem chi tiết assignment")
    p_show.add_argument("type", choices=["assignment"])
    p_show.add_argument("id", type=int)

    # complete
    p_complete = sub.add_parser("complete", help="AI làm bài + submit")
    p_complete.add_argument("id", type=int, help="Assignment ID")

    # quiz
    p_quiz = sub.add_parser("quiz", help="AI đọc quiz và đưa đáp án (bạn tự điền)")
    p_quiz.add_argument("id", type=int, help="Assignment ID")

    # token
    sub.add_parser("token", help="Lấy API token từ Canvas (cần để submit bài)")

    args = parser.parse_args()

    if args.cmd == "token":
        _cmd_get_token()
        return

    if args.cmd == "sync":
        cmd_sync(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "show":
        cmd_show(args)
    elif args.cmd == "complete":
        cmd_complete(args)
    elif args.cmd == "quiz":
        cmd_quiz(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
