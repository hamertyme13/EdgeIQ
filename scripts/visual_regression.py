from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "visual-regression"
BASE_URL = "http://127.0.0.1:8765"
VIEWS = ("Today", "Entries", "Results", "Research")
VIEW_TARGETS = {
    "Today": "dashboard",
    "Entries": "entries",
    "Results": "performance",
    "Research": "analysis",
}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}


def wait_for_server(timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("EdgeIQ visual test server did not become ready.")


def visual_issues(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const blankButtons = [...document.querySelectorAll('button')]
            .filter(visible)
            .filter((button) => !(button.textContent || '').trim() && !button.getAttribute('aria-label'))
            .map((button) => button.id || button.outerHTML.slice(0, 100));
          const clippedButtons = [...document.querySelectorAll('button')]
            .filter(visible)
            .filter((button) => button.scrollWidth > button.clientWidth + 3 || button.scrollHeight > button.clientHeight + 3)
            .map((button) => button.id || (button.textContent || '').trim().slice(0, 60));
          return {
            blank_buttons: blankButtons,
            clipped_buttons: clippedButtons,
            horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth + 3,
            viewport_width: window.innerWidth,
            document_width: document.documentElement.scrollWidth,
          };
        }"""
    )


def capture_view(page: Page, viewport_name: str, view_name: str) -> dict:
    page.locator(f'button[data-view="{VIEW_TARGETS[view_name]}"]:visible').first.click()
    page.wait_for_timeout(900)
    issues = visual_issues(page)
    screenshot = OUTPUT / f"{viewport_name}-{view_name.lower()}.png"
    page.screenshot(path=screenshot, full_page=True)
    if screenshot.stat().st_size < 10_000:
        raise AssertionError(f"{screenshot.name} appears blank or incomplete.")
    if issues["blank_buttons"] or issues["clipped_buttons"] or issues["horizontal_overflow"]:
        raise AssertionError(f"{viewport_name} {view_name} visual issues: {issues}")
    return {"viewport": viewport_name, "view": view_name, "screenshot": str(screenshot), **issues}


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    database_path = Path(tempfile.gettempdir()) / "edgeiq-visual-regression.db"
    database_path.unlink(missing_ok=True)
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database_path}",
        "EDGEIQ_SETTLEMENT_INITIAL_REFRESH_SECONDS": "3600",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", "8765"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    results = []
    try:
        wait_for_server()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for viewport_name, viewport in VIEWPORTS.items():
                page = browser.new_page(viewport=viewport)
                page.goto(BASE_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                if page.locator("#onboarding-skip").is_visible():
                    page.locator("#onboarding-skip").click()
                for view_name in VIEWS:
                    results.append(capture_view(page, viewport_name, view_name))
                page.close()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
    (OUTPUT / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Captured and validated {len(results)} EdgeIQ desktop/mobile views.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
