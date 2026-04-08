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
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        # 1. Vào Canvas → click FlashLine login
        console.print(f"  → Truy cập {CANVAS_BASE_URL}")
        page.goto(CANVAS_BASE_URL, wait_until="networkidle", timeout=30000)
        console.print(f"  [green]✓ Canvas loaded[/green]")
        _click_flashline_login(page)
        console.print(f"  [green]✓ FlashLine click done[/green]")

        # 2. Microsoft SSO: điền email
        console.print(f"  → Step 2: Điền email...")
        _fill_microsoft_email(page, username)
        console.print(f"  [green]✓ Email done[/green]")

        # 3. Microsoft SSO: điền password
        console.print(f"  → Step 3: Điền password...")
        _fill_microsoft_password(page, password)
        console.print(f"  [green]✓ Password done[/green]")

        # 4. MFA (nếu có)
        console.print(f"  → Step 4: Kiểm tra MFA...")
        _handle_mfa(page)
        console.print(f"  [green]✓ MFA done[/green]")

        # 5. "Stay signed in?" prompt của Microsoft
        console.print(f"  → Step 5: Xử lý 'Stay signed in'...")
        _handle_stay_signed_in(page)
        console.print(f"  [green]✓ Stay signed in done[/green]")

        # 6. Chờ về Canvas
        console.print(f"  → Step 6: Chờ về Canvas...")
        if not _wait_for_canvas(page):
            current_url = page.url
            console.print("[red]Đăng nhập thất bại - vẫn còn ở trang ngoài Canvas[/red]")
            console.print(f"[dim]URL hiện tại: {current_url}[/dim]")
            # Chụp screenshot để debug
            try:
                from config import BASE_DIR
                ss = BASE_DIR / "data" / "login_fail.png"
                ss.parent.mkdir(exist_ok=True)
                page.screenshot(path=str(ss))
                console.print(f"[dim]Screenshot: {ss}[/dim]")
            except Exception:
                pass
            browser.close()
            raise RuntimeError(f"Login failed at URL: {current_url}")

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
                    console.print(f"  [green]✓ Clicked FlashLine, now at: {page.url}[/green]")
                    return
            except Exception as e:
                console.print(f"  [dim]Selector {sel} failed: {e}[/dim]")
                continue
        console.print("  [dim]Không tìm thấy nút SSO, tiếp tục...[/dim]")
        console.print(f"  [dim]Current URL: {page.url}[/dim]")
    except Exception as e:
        console.print(f"  [yellow]Error in FlashLine click: {e}[/yellow]")


def _fill_microsoft_email(page, username: str):
    """Điền email/username trên trang Microsoft login."""
    console.print("  → Điền email Microsoft...")
    try:
        # Wait for page to fully load
        page.wait_for_load_state("networkidle", timeout=10000)

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
                    # Focus and clear the field first
                    field.focus()
                    field.clear()
                    # Type character by character for better reliability
                    field.type(username, delay=10)  # 10ms delay between chars
                    # Verify it was filled
                    value = field.input_value()
                    console.print(f"  → Điền email ({sel}), value: {value[:20]}...")
                    filled = True
                    break
            except Exception as e:
                console.print(f"  [dim]Selector {sel} failed: {e}[/dim]")
                continue

        if not filled:
            console.print("  [yellow]Không tìm thấy ô email[/yellow]")
            console.print(f"  [dim]Current URL: {page.url}[/dim]")
            console.print(f"  [dim]Page title: {page.title()}[/dim]")
            return

        page.wait_for_timeout(500)  # Small delay before clicking

        # Try clicking Next button, or press Enter as fallback
        next_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "input[value='Next']",
            "button:has-text('Next')",
        ]
        clicked = False
        for sel in next_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    console.print(f"  → Click Next ({sel})")
                    btn.click(timeout=5000)
                    # Wait for navigation after click
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except:
                        page.wait_for_timeout(3000)  # Fallback timeout
                    clicked = True
                    break
            except Exception as e:
                console.print(f"  [dim]Next button {sel} failed: {e}[/dim]")
                continue

        # Fallback: press Enter key
        if not clicked:
            try:
                console.print("  → Fallback: Press Enter to submit")
                page.press("body", "Enter")
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    page.wait_for_timeout(3000)
                clicked = True
            except Exception as e:
                console.print(f"  [dim]Enter key failed: {e}[/dim]")

        if not clicked:
            console.print("  [yellow]Không tìm thấy nút Next[/yellow]")

    except PlaywrightTimeout:
        console.print("  [yellow]Timeout điền email[/yellow]")


def _fill_microsoft_password(page, password: str):
    """Điền password trên trang Microsoft login."""
    console.print("  → Điền password...")
    try:
        # Wait for page to fully load (Microsoft tách trang email và password)
        page.wait_for_load_state("networkidle", timeout=10000)

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
                    # Focus and clear the field first
                    field.focus()
                    field.clear()
                    # Type character by character for better reliability
                    field.type(password, delay=10)  # 10ms delay between chars
                    # Verify it was filled (don't print password!)
                    value = field.input_value()
                    console.print(f"  → Điền password ({sel}), length: {len(value)}")
                    filled = True
                    break
            except Exception as e:
                console.print(f"  [dim]Password selector {sel} failed: {e}[/dim]")
                continue

        if not filled:
            console.print("  [yellow]Không tìm thấy ô password[/yellow]")
            console.print(f"  [dim]Current URL: {page.url}[/dim]")
            console.print(f"  [dim]Page title: {page.title()}[/dim]")
            return

        page.wait_for_timeout(500)  # Small delay before clicking

        # Click Sign In
        signin_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "input[value='Sign in']",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
        ]
        clicked = False
        for sel in signin_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    console.print(f"  → Click Sign In ({sel})")
                    btn.click(timeout=5000)
                    # Wait for navigation after click
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except:
                        page.wait_for_timeout(3000)  # Fallback timeout
                    clicked = True
                    break
            except Exception as e:
                console.print(f"  [dim]Sign in button {sel} failed: {e}[/dim]")
                continue

        # Fallback: press Enter key
        if not clicked:
            try:
                console.print("  → Fallback: Press Enter to submit")
                page.press("body", "Enter")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except:
                    page.wait_for_timeout(3000)
                clicked = True
            except Exception as e:
                console.print(f"  [dim]Enter key failed: {e}[/dim]")

        if not clicked:
            console.print("  [yellow]Không tìm thấy nút Sign In[/yellow]")
            console.print(f"  [dim]Current URL after form fill: {page.url}[/dim]")

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
                page.wait_for_url(f"**{CANVAS_BASE_URL}**", timeout=60000)
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
        page.wait_for_url("**/dashboard", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        console.print(f"  [green]✓ Canvas URL: {page.url}[/green]")
        return True
    except PlaywrightTimeout:
        current_url = page.url
        console.print(f"  [yellow]Timeout chờ dashboard. Current URL: {current_url}[/yellow]")
        if "kent.instructure.com" in current_url:
            console.print(f"  [green]✓ Đã về Canvas domain (accept fallback)[/green]")
            return True
        else:
            console.print(f"  [red]✗ Vẫn ở ngoài Canvas[/red]")
            return False


def _extract_api_token(page) -> str:
    """Tạo API token từ Canvas profile settings."""
    console.print("  → Lấy API token từ Canvas profile...")
    try:
        page.goto(f"{CANVAS_BASE_URL}/profile/settings", wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(2000)  # Extra wait for JS to load

        # Try multiple selectors for "New Access Token" button
        new_token_selectors = [
            "button:has-text('New Access Token')",
            "a:has-text('New Access Token')",
            "button:has-text('+ New Access Token')",
            "[href*='access_tokens']:has-text('New')",
        ]

        new_token_btn = None
        for sel in new_token_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    new_token_btn = el
                    break
            except:
                continue

        if not new_token_btn:
            console.print("  [yellow]Không tìm thấy nút 'New Access Token', dùng cookies[/yellow]")
            return ""

        new_token_btn.click(timeout=5000)
        page.wait_for_timeout(1500)

        # Điền purpose
        purpose_selectors = [
            "#token_purpose",
            "input[name='purpose']",
            "input[placeholder*='Purpose']",
            "input[placeholder*='purpose']",
        ]

        purpose_field = None
        for sel in purpose_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    purpose_field = el
                    break
            except:
                continue

        if purpose_field:
            purpose_field.fill("canvas-app")
        else:
            console.print("  [yellow]Không tìm thấy ô 'Purpose'[/yellow]")

        # Click Generate Token
        gen_selectors = [
            "button:has-text('Generate Token')",
            "button:has-text('Generate')",
            "input[value='Generate Token']",
        ]

        gen_btn = None
        for sel in gen_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    gen_btn = el
                    break
            except:
                continue

        if gen_btn:
            gen_btn.click()
            page.wait_for_timeout(2000)
        else:
            console.print("  [yellow]Không tìm thấy nút 'Generate'[/yellow]")

        # Lấy token từ modal/display
        token_selectors = [
            "#token-string",
            "#new_token_value",
            "[data-testid='token-value']",
            ".token-value",
            "input.token",
            ".token",
            "code",  # Token often shown in <code> tag
        ]

        token = ""
        for sel in token_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    val = el.input_value() if "input" in sel else el.text_content()
                    if val:
                        token = val.strip()
                        break
            except:
                continue

        if token and len(token) > 10:  # Real token is usually long
            console.print(f"  [green]✓ API token lấy thành công (dài {len(token)} ký tự)[/green]")
            return token
        else:
            console.print(f"  [yellow]Token không hợp lệ hoặc trống, dùng cookies[/yellow]")
            return ""

    except Exception as e:
        console.print(f"  [yellow]Không lấy được API token ({type(e).__name__}: {e}), dùng cookies thay thế[/yellow]")
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
