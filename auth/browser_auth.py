"""
⚠️ DEPRECATED: This module is no longer used in the main application flow.

The Canvas login flow has been refactored to use Canvas API tokens provided by users.
This file contains old Playwright-based authentication code and is kept only for reference.

DO NOT USE in new code. New features should use Canvas API token authentication via
storage/users.py:get_canvas_api_token() or the Canvas API client instead.

For browser extension implementation, design a new auth flow — do NOT reuse this code.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
from rich.console import Console
from config import CANVAS_BASE_URL, BASE_DIR

console = Console()
COOKIES_FILE = BASE_DIR / "session_cookies.json"
TOKEN_FILE = BASE_DIR / "api_token.txt"


def login(username: str = "", password: str = "", headless: bool = True):
    """
    Login to Canvas using Playwright.

    Handles Microsoft account picker:
    1. If account is saved, clicks on it
    2. If not saved, clicks "Use another account" and fills form

    Returns: (cookies, api_token)
    """
    headless = True  # Always headless on servers

    console.print("[bold blue]Logging into Canvas...[/bold blue]")

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
            # 1. Navigate to Canvas SAML login
            console.print(f"  → Accessing Canvas login...")
            saml_url = f"{CANVAS_BASE_URL}/login?authentication_provider=saml"
            page.goto(saml_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Handle Microsoft account picker
            console.print(f"  → Checking for saved accounts...")
            _handle_account_picker(page, username)

            # 3. Fill email form (if "Use another account" was clicked)
            console.print(f"  → Filling email form...")
            _fill_email_form(page, username)

            # 4. Fill password form
            console.print(f"  → Filling password form...")
            _fill_password_form(page, password)

            # 5. Wait for Canvas dashboard
            console.print(f"  → Waiting for Canvas...")
            if not _wait_for_canvas_dashboard(page):
                raise RuntimeError(f"Failed to reach Canvas. Last URL: {page.url}")

            console.print(f"  [green]✓ Successfully logged in![/green]")

            # 6. Extract cookies
            cookies = context.cookies()
            console.print(f"  [green]✓ Extracted {len(cookies)} session cookies[/green]")

            # 7. Try to extract API token
            api_token = _extract_api_token(page)

            # 8. Save session
            _save_session(cookies, api_token)
            browser.close()

            return cookies, api_token

        except Exception as e:
            browser.close()
            raise RuntimeError(f"Login failed: {str(e)}")


def _handle_account_picker(page, username: str):
    """
    Handle Microsoft account picker page.

    If account is saved and visible, click on it.
    Otherwise, click "Use another account" to enter new credentials.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except:
        pass

    page.wait_for_timeout(1000)

    # Try to find and click the saved account matching our username
    try:
        # Look for account button with matching email
        account_buttons = page.locator("div[data-test-id='account-tile'], button:has-text('kent.edu')").all()
        for btn in account_buttons:
            try:
                btn_text = btn.text_content() or ""
                console.print(f"  [dim]Found account: {btn_text[:30]}[/dim]")

                # Check if this is our account
                if username in btn_text or username.split("@")[0] in btn_text:
                    console.print(f"  [dim]✓ Clicking saved account: {btn_text}[/dim]")
                    btn.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    return  # Account was clicked, we're done
            except:
                continue
    except:
        pass

    # Account not found or not visible - click "Use another account"
    try:
        console.print(f"  [dim]Account not saved, clicking 'Use another account'[/dim]")
        use_another_btn = page.locator("button:has-text('Use another account'), div:has-text('Use another account')").first
        if use_another_btn.is_visible(timeout=3000):
            use_another_btn.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            console.print(f"  [dim]✓ Clicked 'Use another account'[/dim]")
            return
    except:
        pass

    console.print(f"  [dim]No account picker found, continuing...[/dim]")


def _fill_email_form(page, username: str):
    """Fill and submit email form."""
    page.wait_for_timeout(1000)

    email_selectors = [
        "input[name='loginfmt']",      # Microsoft standard
        "input[placeholder*='email']",
        "input[placeholder*='Email']",
        "input[type='email']",
        "input[name='email']",
        "input[type='text']:visible",
    ]

    email_filled = False
    for sel in email_selectors:
        try:
            field = page.locator(sel).first
            if field.is_visible(timeout=2000):
                field.click()
                page.wait_for_timeout(200)
                field.clear()
                field.fill(username)
                page.wait_for_timeout(200)
                val = field.input_value()
                if val and len(val) > 0:
                    console.print(f"  [green]✓ Email entered[/green]")
                    email_filled = True
                    break
        except:
            continue

    if not email_filled:
        raise RuntimeError("Could not find email field")

    page.wait_for_timeout(300)

    # Click Next button
    next_buttons = [
        "input[type='submit']",
        "button[type='submit']",
        "button:has-text('Next')",
    ]

    for sel in next_buttons:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(2000)
                console.print(f"  [green]✓ Next clicked[/green]")
                return
        except:
            continue

    # Try pressing Enter
    try:
        page.press("input", "Enter")
        page.wait_for_timeout(2000)
        console.print(f"  [green]✓ Submitted with Enter[/green]")
    except:
        raise RuntimeError("Could not submit email form")


def _fill_password_form(page, password: str):
    """Fill and submit password form."""
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    page.wait_for_timeout(1500)

    password_selectors = [
        "input[name='passwd']",         # Microsoft standard
        "input[placeholder*='password']",
        "input[placeholder*='Password']",
        "input[type='password']",
        "input[name='password']",
    ]

    password_filled = False
    pwd_field = None
    for sel in password_selectors:
        try:
            field = page.locator(sel).first
            if field.is_visible(timeout=5000):
                pwd_field = field
                field.click()
                page.wait_for_timeout(300)
                field.clear()
                page.wait_for_timeout(200)
                field.fill(password)
                page.wait_for_timeout(300)
                val = field.input_value()
                if val and len(val) > 0:
                    console.print(f"  [green]✓ Password entered[/green]")
                    password_filled = True
                    break
        except Exception:
            continue

    if not password_filled:
        raise RuntimeError("Could not find password field")

    page.wait_for_timeout(500)

    # Try clicking Sign In button
    signin_buttons = [
        "input[type='submit']",
        "button[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('Sign In')",
    ]

    submitted = False
    for sel in signin_buttons:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3000):
                console.print(f"  [dim]Clicking sign in button[/dim]")
                btn.click()
                page.wait_for_timeout(3000)
                console.print(f"  [green]✓ Sign in button clicked[/green]")
                submitted = True
                break
        except Exception:
            continue

    # Fallback: Press Enter on password field
    if not submitted and pwd_field:
        try:
            console.print(f"  [dim]Fallback: pressing Enter[/dim]")
            pwd_field.press("Enter")
            page.wait_for_timeout(3000)
            console.print(f"  [green]✓ Submitted with Enter key[/green]")
            submitted = True
        except Exception:
            pass

    if not submitted:
        raise RuntimeError("Could not submit password form - sign in button not found")


def _wait_for_canvas_dashboard(page) -> bool:
    """Wait for successful login - should be on Canvas dashboard."""
    console.print(f"  → Waiting for Canvas (max 30 seconds)...")

    # Wait for URL to change away from Microsoft login
    initial_url = page.url
    start_time = page.evaluate("() => Date.now()")

    while True:
        try:
            current_url = page.url
            console.print(f"  [dim]Current URL: {current_url[:60]}...[/dim]")

            # Check if we reached Canvas
            if "kent.instructure.com" in current_url:
                console.print(f"  [green]✓ Reached Canvas![/green]")
                return True

            # Check if we're still at Microsoft login (bad sign)
            if "login.microsoftonline.com" in current_url and current_url == initial_url:
                # Still at login page - wait a bit more
                page.wait_for_timeout(2000)
                if page.url == initial_url:
                    console.print(f"  [red]✗ Still at Microsoft login - form submission may have failed[/red]")
                    return False
            else:
                # URL changed but not to Canvas - wait for it to navigate
                page.wait_for_timeout(2000)

            # Check elapsed time
            elapsed = (page.evaluate("() => Date.now()") - start_time) / 1000
            if elapsed > 30:
                console.print(f"  [yellow]Timeout after {elapsed:.0f}s[/yellow]")
                return False

        except Exception as e:
            console.print(f"  [dim]Error waiting: {type(e).__name__}[/dim]")
            page.wait_for_timeout(2000)
            current_url = page.url
            if "kent.instructure.com" in current_url:
                return True
            continue


def _extract_api_token(page) -> str:
    """Extract Canvas API token."""
    try:
        page.goto(f"{CANVAS_BASE_URL}/profile/settings", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Find and click "New Access Token"
        for sel in ["button:has-text('New Access Token')", "a:has-text('New Access Token')"]:
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
            field = page.locator("input[name='purpose']").first
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
        for sel in ["code", "#new_token_value", ".token"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    val = el.text_content()
                    if val and len(val) > 10:
                        console.print(f"  [green]✓ API token obtained[/green]")
                        return val.strip()
            except:
                continue

        console.print(f"  [dim]API token not available[/dim]")
        return ""

    except Exception:
        console.print(f"  [dim]Token extraction skipped[/dim]")
        return ""


def _save_session(cookies: list, api_token: str):
    """Save cookies and token."""
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
