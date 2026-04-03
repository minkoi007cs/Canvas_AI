"""
Playwright-based login: Canvas → FlashLine → Microsoft SSO → MFA → Canvas
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from config import CANVAS_BASE_URL, CANVAS_USERNAME, CANVAS_PASSWORD, BASE_DIR

console = Console()
COOKIES_FILE = BASE_DIR / "session_cookies.json"
TOKEN_FILE = BASE_DIR / "api_token.txt"


def login(username: str = "", password: str = "", headless: bool = False):
    username = username or CANVAS_USERNAME
    password = password or CANVAS_PASSWORD

    if not username or not password:
        raise ValueError("Cần username và password trong .env")

    console.print("[bold blue]Đang mở browser để đăng nhập Canvas...[/bold blue]")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        # 1. Vào Canvas → click FlashLine login
        console.print(f"  → Truy cập {CANVAS_BASE_URL}")
        page.goto(CANVAS_BASE_URL, wait_until="networkidle", timeout=30000)
        _click_flashline_login(page)

        # 2. Microsoft SSO: điền email
        _fill_microsoft_email(page, username)

        # 3. Microsoft SSO: điền password
        _fill_microsoft_password(page, password)

        # 4. MFA (nếu có)
        _handle_mfa(page)

        # 5. "Stay signed in?" prompt của Microsoft
        _handle_stay_signed_in(page)

        # 6. Chờ về Canvas
        if not _wait_for_canvas(page):
            console.print("[red]Đăng nhập thất bại - vẫn còn ở trang ngoài Canvas[/red]")
            console.print(f"[dim]URL hiện tại: {page.url}[/dim]")
            browser.close()
            return None, None

        # 7. Lấy API token từ Canvas profile
        api_token = _extract_api_token(page)

        cookies = context.cookies()
        browser.close()

    _save_session(cookies, api_token)
    console.print("[bold green]✓ Đăng nhập thành công![/bold green]")
    return cookies, api_token


def _click_flashline_login(page):
    """Click nút login FlashLine trên trang Canvas."""
    console.print("  → Tìm nút đăng nhập FlashLine...")
    try:
        selectors = [
            "a:has-text('FlashLine')",
            "a[href*='saml']",
            "a[href*='sso']",
            ".btn-primary",
            "a:has-text('Log In')",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    console.print(f"  → Click: {sel}")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    return
            except Exception:
                continue
        console.print("  [dim]Không tìm thấy nút SSO, tiếp tục...[/dim]")
    except Exception:
        pass


def _fill_microsoft_email(page, username: str):
    """Điền email/username trên trang Microsoft login."""
    console.print("  → Điền email Microsoft...")
    try:
        # Microsoft dùng input[name='loginfmt'] cho email
        email_selectors = [
            "input[name='loginfmt']",
            "input[type='email']",
            "input[name='username']",
            "input[name='j_username']",
        ]
        filled = False
        for sel in email_selectors:
            try:
                field = page.locator(sel).first
                if field.is_visible(timeout=5000):
                    field.fill(username)
                    console.print(f"  → Điền email ({sel})")
                    filled = True
                    break
            except Exception:
                continue

        if not filled:
            console.print("  [yellow]Không tìm thấy ô email[/yellow]")
            return

        # Click Next / Submit
        next_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "input[value='Next']",
            "button:has-text('Next')",
        ]
        for sel in next_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=10000)
                    break
            except Exception:
                continue

    except PlaywrightTimeout:
        console.print("  [yellow]Timeout điền email[/yellow]")


def _fill_microsoft_password(page, password: str):
    """Điền password trên trang Microsoft login."""
    console.print("  → Điền password...")
    try:
        # Chờ password field xuất hiện (Microsoft tách trang email và password)
        password_selectors = [
            "input[name='passwd']",
            "input[type='password']",
            "input[name='j_password']",
            "input[name='password']",
        ]
        filled = False
        for sel in password_selectors:
            try:
                field = page.locator(sel).first
                if field.is_visible(timeout=8000):
                    field.fill(password)
                    console.print("  → Điền password")
                    filled = True
                    break
            except Exception:
                continue

        if not filled:
            console.print("  [yellow]Không tìm thấy ô password[/yellow]")
            return

        # Click Sign In
        signin_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "input[value='Sign in']",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
        ]
        for sel in signin_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                    break
            except Exception:
                continue

    except PlaywrightTimeout:
        console.print("  [yellow]Timeout điền password[/yellow]")


def _handle_mfa(page):
    """Xử lý MFA của Microsoft Authenticator."""
    try:
        page.wait_for_timeout(2000)
        url = page.url

        # Detect trang MFA
        is_mfa = any(k in url.lower() for k in ["mfa", "otc", "proofup", "strongauthentication"])

        # Hoặc detect bằng element
        if not is_mfa:
            try:
                # Microsoft MFA code input
                mfa_input = page.locator(
                    "input[name='otc'], input[name='idTxtBx_OTC_0'], input[placeholder*='code']"
                ).first
                is_mfa = mfa_input.is_visible(timeout=3000)
            except Exception:
                pass

        # Detect "Approve sign-in request" (push notification)
        if not is_mfa:
            try:
                push_text = page.locator("text='Approve sign-in request', text='Check your phone'").first
                is_mfa = push_text.is_visible(timeout=3000)
            except Exception:
                pass

        if not is_mfa:
            return

        console.print("\n[bold yellow]⚠ Phát hiện màn hình MFA (Microsoft)[/bold yellow]")

        # Kiểm tra loại MFA
        has_code_input = False
        try:
            code_field = page.locator(
                "input[name='otc'], input[name='idTxtBx_OTC_0'], input[placeholder*='code'], input[maxlength='6']"
            ).first
            has_code_input = code_field.is_visible(timeout=3000)
        except Exception:
            pass

        if has_code_input:
            # Loại TOTP / SMS code
            mfa_code = console.input("[bold yellow]Nhập MFA code (6 chữ số): [/bold yellow]").strip()
            code_field.fill(mfa_code)
            page.wait_for_timeout(500)

            # Submit - Microsoft dùng nhiều selector khác nhau
            submit_selectors = [
                "#idSubmit_SAOTCC_Continue",
                "input[type='submit']",
                "button[type='submit']",
                "button:has-text('Verify')",
                "button:has-text('Sign in')",
            ]
            for sel in submit_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        page.wait_for_load_state("networkidle", timeout=15000)
                        console.print("[green]✓ MFA code submitted[/green]")
                        break
                except Exception:
                    continue
        else:
            # Push notification - chờ user approve trên điện thoại
            console.print("[yellow]Kiểm tra điện thoại → Approve notification trong Microsoft Authenticator[/yellow]")
            console.print("[dim]App đang chờ (tối đa 60 giây)...[/dim]")
            try:
                page.wait_for_url(f"*{CANVAS_BASE_URL}*", timeout=60000)
                console.print("[green]✓ MFA approved[/green]")
            except PlaywrightTimeout:
                console.print("[yellow]Timeout MFA, tiếp tục...[/yellow]")

    except Exception as e:
        console.print(f"  [dim]MFA handler: {e}[/dim]")


def _handle_stay_signed_in(page):
    """Xử lý 'Stay signed in?' prompt của Microsoft."""
    try:
        page.wait_for_timeout(1500)
        # "Yes" button trên prompt này
        yes_selectors = [
            "#idSIButton9",
            "input[value='Yes']",
            "button:has-text('Yes')",
        ]
        for sel in yes_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    console.print("  → 'Stay signed in?' → Yes")
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=10000)
                    return
            except Exception:
                continue
    except Exception:
        pass


def _wait_for_canvas(page) -> bool:
    """Chờ về Canvas. Trả về True nếu thành công."""
    console.print("  → Chờ về Canvas dashboard...")
    try:
        page.wait_for_url(f"**kent.instructure.com**", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        console.print(f"  [green]✓ Canvas URL: {page.url}[/green]")
        return True
    except PlaywrightTimeout:
        return "kent.instructure.com" in page.url


def _extract_api_token(page) -> str:
    """Tạo API token từ Canvas profile settings."""
    console.print("  → Lấy API token từ Canvas profile...")
    try:
        page.goto(f"{CANVAS_BASE_URL}/profile/settings", wait_until="networkidle", timeout=15000)

        # Click "New Access Token" button
        new_token_btn = page.locator(
            "button:has-text('New Access Token'), a:has-text('New Access Token')"
        ).first
        new_token_btn.click(timeout=5000)

        # Điền purpose
        purpose_field = page.locator(
            "#token_purpose, input[name='purpose'], input[placeholder*='Purpose']"
        ).first
        purpose_field.wait_for(state="visible", timeout=5000)
        purpose_field.fill("canvas-app")

        # Click Generate Token
        page.locator(
            "button:has-text('Generate Token'), input[value='Generate Token']"
        ).first.click()

        # Lấy token từ modal
        token_el = page.locator(
            "#token-string, .token, input.token, [data-testid='token-value'], #new_token_value"
        ).first
        token_el.wait_for(state="visible", timeout=5000)
        token = token_el.input_value() or token_el.text_content()
        token = token.strip()

        if token:
            console.print(f"  [green]✓ API token lấy thành công[/green]")
            return token
        else:
            console.print("  [yellow]Không đọc được token, sẽ dùng cookies[/yellow]")
            return ""

    except Exception as e:
        console.print(f"  [yellow]Không lấy được API token ({e}), dùng cookies thay thế[/yellow]")
        return ""


def _save_session(cookies: list, api_token: str):
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    if api_token:
        TOKEN_FILE.write_text(api_token)
    console.print(f"  [dim]Session lưu tại {COOKIES_FILE}[/dim]")


def load_saved_cookies():
    if COOKIES_FILE.exists():
        return json.loads(COOKIES_FILE.read_text())
    return None


def load_saved_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return ""
