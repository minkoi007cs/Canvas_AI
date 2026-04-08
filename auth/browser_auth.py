"""
Interactive Canvas login - Opens browser for user to log in manually,
then extracts session cookies for API access.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from config import CANVAS_BASE_URL, BASE_DIR

console = Console()
COOKIES_FILE = BASE_DIR / "session_cookies.json"
TOKEN_FILE = BASE_DIR / "api_token.txt"


def login(username: str = "", password: str = "", headless: bool = False):
    """
    Open Canvas login page in browser for user to manually log in.
    Once on Canvas dashboard, extract and save session cookies.

    Returns: (cookies, api_token)
    """
    console.print("[bold blue]Opening Canvas login page in browser...[/bold blue]")
    console.print("[yellow]⚠️  Please log in manually using your Canvas credentials[/yellow]")

    with sync_playwright() as p:
        # Open NON-headless browser so user can see and interact with login page
        browser = p.chromium.launch(
            headless=False,  # Important: show browser window
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # Navigate to Canvas login page
            console.print(f"  → Loading Canvas login page...")
            page.goto(f"{CANVAS_BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)

            console.print(f"  [green]✓ Login page loaded[/green]")
            console.print(f"")
            console.print(f"  [bold cyan]Browser opened - please log in manually:[/bold cyan]")
            console.print(f"  1. Enter your Canvas (FlashLine) credentials")
            console.print(f"  2. Complete any MFA/2FA prompts")
            console.print(f"  3. Once you reach the Dashboard, app will auto-detect and continue")
            console.print(f"")

            # Wait for user to log in - detect when they reach the dashboard
            max_wait = 600  # 10 minutes
            waited = 0
            check_interval = 2  # Check every 2 seconds

            while waited < max_wait:
                try:
                    current_url = page.url

                    # Check if we're on Canvas domain (logged in)
                    if "kent.instructure.com" in current_url and ("/dashboard" in current_url or "/courses" in current_url or "/groups" in current_url):
                        console.print(f"")
                        console.print(f"  [green]✓ Login detected![/green]")
                        console.print(f"  [dim]Current page: {current_url[:80]}[/dim]")
                        break

                    page.wait_for_timeout(check_interval * 1000)
                    waited += check_interval

                except PlaywrightTimeout:
                    waited += check_interval
                    if waited % 30 == 0:
                        console.print(f"  [dim]Waiting for login... ({waited}s)[/dim]")
                    continue

            if waited >= max_wait:
                console.print(f"[red]✗ Login timeout - not on Canvas after 10 minutes[/red]")
                browser.close()
                raise RuntimeError("Login timeout")

            # User is now logged in - extract cookies
            console.print(f"  → Extracting session cookies...")
            cookies = context.cookies()
            console.print(f"  [green]✓ Got {len(cookies)} session cookies[/green]")

            # Try to extract API token
            console.print(f"  → Attempting to extract API token...")
            api_token = _extract_api_token(page)

            # Save session
            _save_session(cookies, api_token)
            browser.close()

            console.print(f"[bold green]✓ Login successful![/bold green]")
            return cookies, api_token

        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            browser.close()
            raise


def _extract_api_token(page) -> str:
    """Extract Canvas API token from profile settings."""
    try:
        console.print(f"  [dim]Navigating to Canvas profile settings...[/dim]")
        page.goto(f"{CANVAS_BASE_URL}/profile/settings", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Try to find "New Access Token" button
        selectors = [
            "button:has-text('New Access Token')",
            "a:has-text('New Access Token')",
            "[href*='access_tokens']:has-text('New')",
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

        # Extract token from various possible locations
        selectors = [
            "#new_token_value",
            "[data-testid='token-value']",
            "code",
            ".token",
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

        console.print(f"  [yellow]Could not extract API token (not critical)[/yellow]")
        return ""

    except Exception as e:
        console.print(f"  [dim]Token extraction skipped: {e}[/dim]")
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
