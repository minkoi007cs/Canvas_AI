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
    """Login to Canvas using Playwright. Returns (cookies, api_token)."""
    username = username or CANVAS_USERNAME
    password = password or CANVAS_PASSWORD

    if not username or not password:
        raise ValueError("Canvas username and password required")

    console.print("[bold blue]Opening browser for Canvas login...[/bold blue]")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # 1. Navigate to Canvas
            console.print(f"  [cyan]→ Accessing Canvas...[/cyan]")
            page.goto(CANVAS_BASE_URL, wait_until="domcontentloaded", timeout=30000)
            console.print(f"  [green]✓ Canvas page loaded[/green]")

            # 2. Click FlashLine login button
            console.print(f"  [cyan]→ Finding FlashLine login button...[/cyan]")
            _click_login_button(page)
            console.print(f"  [green]✓ FlashLine login initiated[/green]")

            # 3. Wait for and fill Microsoft email form
            console.print(f"  [cyan]→ Filling Microsoft email form...[/cyan]")
            _fill_email_form(page, username)
            console.print(f"  [green]✓ Email form submitted[/green]")

            # 4. Wait for and fill Microsoft password form
            console.print(f"  [cyan]→ Filling Microsoft password form...[/cyan]")
            _fill_password_form(page, password)
            console.print(f"  [green]✓ Password form submitted[/green]")

            # 5. Handle MFA if present
            console.print(f"  [cyan]→ Checking for MFA...[/cyan]")
            _handle_mfa(page)

            # 6. Handle "Stay signed in" prompt
            console.print(f"  [cyan]→ Handling Microsoft prompts...[/cyan]")
            _handle_stay_signed_in(page)

            # 7. Wait for return to Canvas
            console.print(f"  [cyan]→ Waiting for Canvas dashboard...[/cyan]")
            if not _wait_for_canvas(page):
                current_url = page.url
                console.print(f"[red]✗ Login failed - stuck at: {current_url}[/red]")
                # Save screenshot
                try:
                    ss = BASE_DIR / "data" / "login_failure.png"
                    ss.parent.mkdir(exist_ok=True)
                    page.screenshot(path=str(ss))
                    console.print(f"[dim]Debug screenshot: {ss}[/dim]")
                except:
                    pass
                raise RuntimeError(f"Login failed at URL: {current_url}")

            # 8. Extract API token
            console.print(f"  [cyan]→ Extracting API token...[/cyan]")
            api_token = _extract_api_token(page)

            # 9. Save session
            cookies = context.cookies()
            _save_session(cookies, api_token)

            browser.close()
            console.print("[bold green]✓ Login successful![/bold green]")
            return cookies, api_token

        except Exception as e:
            browser.close()
            raise


def _click_login_button(page):
    """Click the FlashLine login button on Canvas homepage."""
    selectors = [
        "a:has-text('FlashLine')",
        "a[href*='saml']",
        "a[href*='sso']",
        ".btn-primary:visible",
        "a:has-text('Log In')",
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3000):
                btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                return
        except:
            continue

    # If no button found, page might already be at login
    console.print("  [dim]No FlashLine button found, continuing...[/dim]")


def _fill_email_form(page, username: str):
    """Fill and submit the Microsoft email form."""
    # Wait for email form to be visible
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except:
        pass

    # Try common email field selectors
    email_selectors = [
        "input[name='loginfmt']",     # Microsoft standard
        "input[type='email']",
        "input[name='username']",
        "#i0116",                      # Microsoft Office 365
    ]

    email_filled = False
    for sel in email_selectors:
        try:
            field = page.locator(sel).first
            if field.is_visible(timeout=5000):
                field.click()
                field.clear()
                field.fill(username)
                email_filled = True
                break
        except:
            continue

    if not email_filled:
        raise RuntimeError(f"Could not find email field. URL: {page.url}")

    # Submit form - try multiple methods
    page.wait_for_timeout(300)

    # Method 1: Click Next button
    submit_selectors = [
        "input[type='submit']",
        "button[type='submit']",
        "#idSIButton9",              # Microsoft standard button ID
        "button:has-text('Next')",
    ]

    submitted = False
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(2000)
                submitted = True
                break
        except:
            continue

    # Method 2: Press Enter
    if not submitted:
        try:
            page.press("body", "Enter")
            page.wait_for_timeout(2000)
            submitted = True
        except:
            pass

    # Method 3: JavaScript submit
    if not submitted:
        try:
            page.evaluate("document.querySelector('form')?.submit()")
            page.wait_for_timeout(2000)
        except:
            pass


def _fill_password_form(page, password: str):
    """Fill and submit the Microsoft password form."""
    # Wait for password form to appear
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except:
        pass

    page.wait_for_timeout(500)

    # Try common password field selectors
    password_selectors = [
        "input[name='passwd']",       # Microsoft standard
        "input[type='password']",
        "#i0118",                      # Microsoft Office 365
    ]

    password_filled = False
    for sel in password_selectors:
        try:
            field = page.locator(sel).first
            if field.is_visible(timeout=8000):
                field.click()
                field.clear()
                field.fill(password)
                password_filled = True
                break
        except:
            continue

    if not password_filled:
        raise RuntimeError(f"Could not find password field. URL: {page.url}")

    # Submit form - try multiple methods
    page.wait_for_timeout(300)

    # Method 1: Click Sign In button
    submit_selectors = [
        "input[type='submit']",
        "button[type='submit']",
        "#idSIButton9",              # Microsoft standard button ID
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
    ]

    submitted = False
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(2000)
                submitted = True
                break
        except:
            continue

    # Method 2: Press Enter
    if not submitted:
        try:
            page.press("body", "Enter")
            page.wait_for_timeout(2000)
            submitted = True
        except:
            pass

    # Method 3: JavaScript submit
    if not submitted:
        try:
            page.evaluate("document.querySelector('form')?.submit()")
            page.wait_for_timeout(2000)
        except:
            pass


def _handle_mfa(page):
    """Handle Microsoft MFA if present."""
    try:
        page.wait_for_timeout(1000)
        url = page.url

        # Check if on MFA page
        is_mfa = any(k in url.lower() for k in ["mfa", "otc", "proofup", "challenge"])

        if not is_mfa:
            try:
                mfa_field = page.locator("input[name='otc'], input[placeholder*='code']").first
                is_mfa = mfa_field.is_visible(timeout=2000)
            except:
                pass

        if is_mfa:
            console.print("[bold yellow]⚠ MFA detected - please complete authentication[/bold yellow]")
            # Wait for user to complete MFA or for redirect
            try:
                page.wait_for_url("**/dashboard", timeout=120000)
            except:
                # Try to wait for Canvas domain at least
                page.wait_for_timeout(5000)
    except:
        pass


def _handle_stay_signed_in(page):
    """Handle Microsoft 'Stay signed in?' prompt."""
    try:
        page.wait_for_timeout(500)

        yes_selectors = [
            "#idSIButton9",
            "input[value='Yes']",
            "button:has-text('Yes')",
        ]

        for sel in yes_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1000)
                    break
            except:
                continue
    except:
        pass


def _wait_for_canvas(page) -> bool:
    """Wait for return to Canvas dashboard."""
    try:
        page.wait_for_url("**/dashboard", timeout=30000)
        console.print(f"  [green]✓ Canvas URL: {page.url}[/green]")
        return True
    except PlaywrightTimeout:
        current_url = page.url
        console.print(f"  [yellow]Timeout waiting for dashboard[/yellow]")
        console.print(f"  [dim]Current URL: {current_url}[/dim]")

        # Fallback: accept if we're on Canvas domain
        if "kent.instructure.com" in current_url or "instructure.com" in current_url:
            console.print(f"  [green]✓ On Canvas domain[/green]")
            return True

        return False


def _extract_api_token(page) -> str:
    """Extract Canvas API token from profile settings."""
    try:
        page.goto(f"{CANVAS_BASE_URL}/profile/settings", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Try to find "New Access Token" button
        selectors = [
            "button:has-text('New Access Token')",
            "a:has-text('New Access Token')",
            "[href*='access_tokens']",
        ]

        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1500)
                    break
            except:
                continue

        # Fill purpose
        try:
            field = page.locator("input#token_purpose, input[name='purpose']").first
            if field.is_visible(timeout=2000):
                field.fill("canvas-app")
        except:
            pass

        # Click Generate
        try:
            btn = page.locator("button:has-text('Generate')").first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(2000)
        except:
            pass

        # Extract token
        selectors = [
            "#new_token_value",
            "[data-testid='token-value']",
            "code",
        ]

        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    val = el.input_value() if "input" in sel else el.text_content()
                    if val and len(val) > 10:
                        console.print(f"  [green]✓ API token extracted[/green]")
                        return val.strip()
            except:
                continue

        console.print(f"  [yellow]Could not extract API token, using cookies instead[/yellow]")
        return ""

    except Exception as e:
        console.print(f"  [yellow]Token extraction failed: {e}[/yellow]")
        return ""


def _save_session(cookies: list, api_token: str):
    """Save cookies and token to files."""
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    if api_token:
        TOKEN_FILE.write_text(api_token)
    console.print(f"  [green]✓ Session saved[/green]")


def load_saved_cookies():
    """Load saved session cookies."""
    if COOKIES_FILE.exists():
        return json.loads(COOKIES_FILE.read_text())
    return None


def load_saved_token() -> str:
    """Load saved API token."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return ""
