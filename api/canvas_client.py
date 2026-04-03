"""
Canvas API client - dùng API token (ưu tiên) hoặc cookies.
"""
import requests
from rich.console import Console
from config import CANVAS_API_URL, CANVAS_BASE_URL

console = Console()


class CanvasClient:
    def __init__(self, cookies: list = None, api_token: str = ""):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "canvas-app/1.0"})

        if api_token:
            self.session.headers.update({"Authorization": f"Bearer {api_token}"})
            console.print("[green]✓ Dùng API token[/green]")
        elif cookies:
            self._load_cookies(cookies)
            console.print("[dim]Dùng session cookies[/dim]")
        else:
            raise ValueError("Cần api_token hoặc cookies")

    def _load_cookies(self, cookies: list):
        for cookie in cookies:
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/"),
            )

    def get(self, endpoint: str, params: dict = None):
        url = f"{CANVAS_API_URL}{endpoint}"
        params = params or {}
        params.setdefault("per_page", 100)

        all_results = []
        while url:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                all_results.extend(data)
                url = self._next_page(resp)
                params = {}
            else:
                return data

        return all_results

    def post(self, endpoint: str, data: dict = None, files=None):
        url = f"{CANVAS_API_URL}{endpoint}"
        if files:
            resp = self.session.post(url, data=data, files=files)
        else:
            resp = self.session.post(url, json=data)
        resp.raise_for_status()
        return resp.json()

    def download_file(self, url: str, dest_path) -> bool:
        try:
            resp = self.session.get(url, stream=True)
            resp.raise_for_status()
            with open(str(dest_path), "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            console.print(f"[red]Lỗi download {url}: {e}[/red]")
            return False

    def _next_page(self, resp: requests.Response):
        link_header = resp.headers.get("Link", "")
        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                return part.split(";")[0].strip().strip("<>")
        return None
