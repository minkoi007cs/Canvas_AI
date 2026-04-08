"""
Canvas login via Playwright - automates FlashLine SSO login
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from config import CANVAS_BASE_URL, BASE_DIR

console = Console()
COOKIES_FILE = BASE_DIR / "session_cookies.json"
TOKEN_FILE = BASE_DIR / "api_token.txt"


def login(username: str = "", password: str = "", headless: bool = True):
    """
    Login to Canvas using Playwright.

    Always uses headless=True for automation since manual login
    requires user to type credentials which we handle programmatically.

    Returns: (cookies, api_token)
    """
    # ALWAYS use headless mode - no X server available on servers
    headless = True

    console.print("[bold blue]Logging into Canvas...[/bold blue]")
    if not headless:
        console.print("[yellow]⚠️  Browser window will open - complete login manually[/yellow]")

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
            # 1. Try direct SAML login URL (Kent State's FlashLine method)
            console.print(f"  → Attempting Canvas SAML login...")
            saml_url = f"{CANVAS_BASE_URL}/login?authentication_provider=saml"
            page.goto(saml_url, wait_until="domcontentloaded", timeout=30000)

            # 2. Wait for and fill the email/username field
            console.print(f"  → Looking for login form...")
            _fill_login_form(page, username, password)

            # 3. Wait for successful login (reach Canvas dashboard or courses page)
            console.print(f"  → Waiting for Canvas dashboard...")
            if not _wait_for_canvas_dashboard(page):
                raise RuntimeError(f"Failed to reach Canvas dashboard. Last URL: {page.url}")

            console.print(f"  [green]✓ Successfully logged in![/green]")

            # 4. Extract cookies
            cookies = context.cookies()
            console.print(f"  [green]✓ Extracted {len(cookies)} session cookies[/green]")

            # 5. Try to extract API token
            api_token = _extract_api_token(page)

            # 6. Save session
            _save_session(cookies, api_token)
            browser.close()

            return cookies, api_token

        except Exception as e:
            browser.close()
            raise RuntimeError(f"Login failed: {str(e)}")


def _fill_login_form(page, username: str, password: str):
    """Fill and submit the Canvas/Shibboleth login form."""
    page.wait_for_timeout(1000)

    # List of possible selectors for Shibboleth form fields
    username_selectors = [
        "input[name='j_username']",      # Shibboleth standard
        "input#j_username",
        "input[name='username']",
        "input[type='text']",
    ]

    password_selectors = [
        "input[name='j_password']",      # Shibboleth standard
        "input#j_password",
        "input[name='password']",
        "input[type='password']",
    ]

    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('Login')",
        "button:has-text('Log in')",
    ]

    # Fill username
    username_filled = False
    for sel in username_selectors:
        try:
            field = page.locator(sel).first
            if field.is_visible(timeout=3000):
                field.clear()
                field.fill(username)
                console.print(f"  [dim]✓ Username entered[/dim]")
                username_filled = True
                break
        except:
            continue

    if not username_filled:
        # Debug: show what inputs we found on the page
        console.print(f"")
        console.print(f"  [yellow]✗ Could not find username field![/yellow]")
        console.print(f"  [dim]Current URL: {page.url}[/dim]")
        console.print(f"  [dim]Page title: {page.title()}[/dim]")
        console.print(f"")

        try:
            inputs = page.locator("input").all()
            console.print(f"  [yellow]Found {len(inputs)} input element(s):[/yellow]")
            for i, inp in enumerate(inputs):
                try:
                    name = inp.get_attribute("name") or "(no name)"
                    inp_id = inp.get_attribute("id") or "(no id)"
                    inp_type = inp.get_attribute("type") or "text"
                    placeholder = inp.get_attribute("placeholder") or ""
                    visible = inp.is_visible(timeout=1000)
                    console.print(f"    {i+1}. name='{name}', id='{inp_id}', type='{inp_type}', placeholder='{placeholder}', visible={visible}")
                except Exception as e:
                    console.print(f"    {i+1}. [error reading: {e}]")
        except Exception as e:
            console.print(f"  [dim]Error listing inputs: {e}[/dim]")

        # Try to save screenshot for visual debugging
        try:
            ss_path = BASE_DIR / "data" / "login_form_debug.png"
            ss_path.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(ss_path))
            console.print(f"  [dim]Screenshot saved: {ss_path}[/dim]")
        except:
            pass

        console.print(f"")
        raise RuntimeError("Could not find username field on login page")

    page.wait_for_timeout(300)

    # Fill password
    password_filled = False
    for sel in password_selectors:
        try:
            field = page.locator(sel).first
            if field.is_visible(timeout=3000):
                field.clear()
                field.fill(password)
                console.print(f"  [dim]✓ Password entered[/dim]")
                password_filled = True
                break
        except:
            continue

    if not password_filled:
        raise RuntimeError("Could not find password field on login page")

    page.wait_for_timeout(300)

    # Click submit button
    submitted = False
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                console.print(f"  [dim]✓ Form submitted[/dim]")
                submitted = True
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                break
        except:
            continue

    if not submitted:
        # Try pressing Enter as fallback
        try:
            page.press("input[type='password']", "Enter")
            console.print(f"  [dim]✓ Submitted via Enter key[/dim]")
            page.wait_for_timeout(3000)
        except:
            raise RuntimeError("Could not submit login form")


def _wait_for_canvas_dashboard(page) -> bool:
    """Wait for successful login - user should be on Canvas dashboard or courses page."""
    try:
        # Wait for URL to contain Canvas domain AND one of these paths
        dashboard_patterns = [
            "**/dashboard",
            "**/courses",
            "**/groups",
            "kent.instructure.com",
        ]

        for pattern in dashboard_patterns:
            try:
                page.wait_for_url(pattern, timeout=15000)
                return True
            except:
                continue

        # If URL pattern didn't match, check if we're on Canvas at all
        current_url = page.url
        if "kent.instructure.com" in current_url:
            console.print(f"  [dim]At Canvas: {current_url[:80]}[/dim]")
            return True

        return False

    except PlaywrightTimeout:
        return False


def _extract_api_token(page) -> str:
    """Extract Canvas API token from profile settings."""
    try:
        page.goto(f"{CANVAS_BASE_URL}/profile/settings", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Try to find and click "New Access Token" button
        selectors = [
            "button:has-text('New Access Token')",
            "a:has-text('New Access Token')",
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

        # Fill purpose field if it exists
        try:
            field = page.locator("input[name='purpose']").first
            if field.is_visible(timeout=2000):
                field.fill("canvas-app")
        except:
            pass

        # Click Generate button
        try:
            btn = page.locator("button:has-text('Generate')").first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(2000)
        except:
            pass

        # Try to extract token
        token_selectors = [
            "code",
            "#new_token_value",
            "[data-testid='token-value']",
            ".token",
        ]

        for sel in token_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    val = el.text_content()
                    if val and len(val) > 10:
                        console.print(f"  [green]✓ API token obtained[/green]")
                        return val.strip()
            except:
                continue

        console.print(f"  [dim]API token not available (will use cookies)[/dim]")
        return ""

    except Exception as e:
        console.print(f"  [dim]Token extraction skipped: {type(e).__name__}[/dim]")
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
