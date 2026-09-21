from __future__ import annotations

import json
import os
import socket
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


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


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
    if view_name == "Research":
        page.locator('.consumer-more').evaluate('(element) => { element.open = true; }')
        page.locator('button[data-display-mode="advanced"]').click()
        page.locator('.consumer-more').evaluate('(element) => { element.open = false; }')
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
    global BASE_URL
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").unlink(missing_ok=True)
    database_path = Path(tempfile.gettempdir()) / "edgeiq-visual-regression.db"
    database_path.unlink(missing_ok=True)
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database_path}",
        "EDGEIQ_SETTLEMENT_INITIAL_REFRESH_SECONDS": "3600",
    }
    port = available_port()
    BASE_URL = f"http://127.0.0.1:{port}"
    server_log = OUTPUT / "server.log"
    log_handle = server_log.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
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
                results.extend(capture_research_details(page, viewport_name))
                results.append(capture_entry_summary(page, viewport_name))
                results.append(capture_model_track_record(page, viewport_name))
                results.append(capture_best_lines(page, viewport_name))
                page.close()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        log_handle.close()
    (OUTPUT / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Captured and validated {len(results)} EdgeIQ desktop/mobile views.")
    return 0


def capture_model_track_record(page: Page, viewport_name: str) -> dict:
    page.route("**/api/analytics/model-track-record?*", lambda route: route.fulfill(json={
        "locked_predictions": 12, "settled_predictions": 8, "wins": 5, "losses": 3,
        "pushes": 0, "unresolved_or_excluded": 4, "truncated": False,
        "counting_note": "Fixture: separate model/provider records.",
        "versions": [{"model_version": "v2.4", "platform": "PrizePicks", "direction": "Over",
                      "settled_predictions": 8, "small_sample": True, "actual_hit_rate": 62.5,
                      "predicted_hit_rate": 60, "calibration_gap": 2.5, "brier_score": .22}],
    }))
    page.evaluate("setView('performance'); document.querySelector('.consumer-model-track').open = true")
    page.locator('#model-track-form input[name="sport"]').fill("WNBA")
    page.locator('#model-track-form button').click()
    page.locator('.model-track-segment').wait_for()
    assert "Small sample" in page.locator('#model-track-output').inner_text()
    page.locator('.consumer-model-track').scroll_into_view_if_needed()
    issues = visual_issues(page)
    assert not issues["horizontal_overflow"], issues
    assert not issues["clipped_buttons"], issues
    screenshot = OUTPUT / f"{viewport_name}-model-track-record.png"
    page.screenshot(path=screenshot, full_page=True)
    page.unroute("**/api/analytics/model-track-record?*")
    return {"viewport": viewport_name, "view": "Model track record", "screenshot": str(screenshot), **issues}


def capture_entry_summary(page: Page, viewport_name: str) -> dict:
    page.evaluate("""() => {
        setView('entries');
        const data = {
            entry: {platform:'PrizePicks', props:[
                {player:'Example Player One',team:'AAA',game:'AAA @ BBB',stat:'Points',direction:'Over'},
                {player:'Example Player Two',team:'BBB',game:'AAA @ BBB',stat:'Rebounds',direction:'Under'}]},
            risk:{level:'Medium'}, platform_value:{payout_verified:false},
            payout_analysis:{displayed_multiplier:3,expected_value:15},
            model_payout_analysis:{all_hit_probability:30,independent_all_hit_probability:28,correlation_matrix:[[1,.2],[.2,1]]}
        };
        const panel = document.getElementById('entry-analysis');
        panel.innerHTML = window.EdgeIQEntrySummary.render(data, escapeHtml);
        panel.querySelector('details').open = true;
        panel.scrollIntoView();
    }""")
    panel = page.locator(".consumer-entry-summary")
    assert "Unverified payout" in panel.inner_text()
    assert "2.0 percentage points" in panel.inner_text()
    assert "AAA @ BBB (2 legs)" in panel.inner_text()
    issues = visual_issues(page)
    assert not issues["horizontal_overflow"], issues
    assert not issues["clipped_buttons"], issues
    screenshot = OUTPUT / f"{viewport_name}-entry-summary.png"
    page.screenshot(path=screenshot, full_page=True)
    return {"viewport": viewport_name, "view": "Entry summary", "screenshot": str(screenshot), **issues}


def capture_research_details(page: Page, viewport_name: str) -> list[dict]:
    """Exercise populated research, not just the empty-state shell."""
    payload = {
        "player": "Example Player", "sport": "WNBA", "stat": "Points",
        "history_count": 0, "active_props": [], "line": 19.5,
        "edgeiq_score": {
            "score": 45.0, "label": "Pass", "components": {"model": 60, "history": 0},
            "penalties": {"evidence_cap": -5},
            "summary": "Small sample: fewer than 20 comparable player games.",
            "meaning": "Research score, not win probability or permission to place a paid entry.",
            "restrictions": ["This model segment has not cleared paid-use evidence requirements."],
        },
    }
    page.route("**/api/players/*/research?*", lambda route: route.fulfill(json=payload))
    page.evaluate("""async () => {
        document.getElementById('research-player').value = 'Example Player';
        document.getElementById('research-stat').value = 'Points';
        await loadPlayerResearch({preventDefault() {}});
    }""")
    panel = page.locator("#player-research-result")
    assert panel.locator(".consumer-research-section").count() == 7
    assert panel.locator(".player-workspace-nav a").count() == 8
    assert "Research only" in panel.locator(".player-workspace-overview").inner_text()
    panel.locator(".player-workspace-nav a").filter(has_text="Model Performance").click()
    assert panel.locator("details[open]").count() == 1
    panel.locator("details[open]").evaluate_all("els => els.forEach(el => el.open = false)")
    assert panel.locator(".consumer-research-section[open]").count() == 0
    results = []
    for expanded in (False, True):
        if expanded:
            panel.locator("summary").evaluate_all("els => els.forEach(el => el.parentElement.open = true)")
            assert "Unavailable" in panel.inner_text()
        issues = visual_issues(page)
        assert not issues["horizontal_overflow"], issues
        assert not issues["clipped_buttons"], issues
        suffix = "expanded" if expanded else "overview"
        screenshot = OUTPUT / f"{viewport_name}-research-{suffix}.png"
        page.screenshot(path=screenshot, full_page=True)
        results.append({"viewport": viewport_name, "view": f"Research {suffix}",
                        "screenshot": str(screenshot), **issues})
    page.unroute("**/api/players/*/research?*")
    return results


def capture_best_lines(page: Page, viewport_name: str) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from web.application.best_lines_service import best_lines_payload

    offer = {"sport": "WNBA", "stat": "Points", "game": "Example A @ Example B",
             "game_time": "2026-09-12T20:00:00Z", "line_offer_type": "standard"}
    payload = best_lines_payload({"player": "Example Player", "stat": "Points", "sport": "WNBA",
                                 "lines": [{**offer, "platform": "PrizePicks", "line": 20.5},
                                           {**offer, "platform": "Underdog", "line": 21.5}]})
    page.route("**/api/market/best-lines?*", lambda route: route.fulfill(json=payload))
    page.locator('button[data-view="best-lines"]:visible').first.click()
    page.locator('.consumer-more').evaluate('(element) => { element.open = true; }')
    page.locator('button[data-display-mode="basic"]').click()
    page.locator('.consumer-more').evaluate('(element) => { element.open = false; }')
    assert page.locator("#best-lines").is_visible()
    page.locator('button[data-view="analysis"]:visible').first.click()
    assert page.locator("#analysis").is_visible()
    assert page.locator("#view-title").inner_text() == "Players"
    assert page.locator('[data-view="analysis"]:visible').first.get_attribute('aria-current') == 'page'
    page.evaluate('setView("unknown-destination")')
    assert page.locator('#analysis').is_visible()
    assert page.locator('#dashboard #data-health-list').count() == 0
    assert page.locator('#systems #data-health-list').count() == 1
    assert page.locator('#dashboard #decision-desk').count() == 0
    for pane in ['value', 'alerts', 'builder', 'board']:
        page.locator('.consumer-more > summary').click()
        page.locator(f'.consumer-more [data-workspace-jump="decision-desk:{pane}"]').click()
        assert page.locator('#tools').is_visible()
        assert page.locator(f'#decision-desk [data-workspace-pane="{pane}"]').is_visible()
        assert page.locator('body').get_attribute('data-display-mode') == 'basic'
    page.evaluate('setView("props")')
    assert page.locator('#tools').is_visible()
    assert page.locator('#decision-desk [data-workspace-pane="board"]').is_visible()
    page.screenshot(path=OUTPUT / f'{viewport_name}-tools.png', full_page=True)
    page.locator('.consumer-more > summary').click()
    page.locator('[data-more-target="runtime-status-title"]').click()
    assert page.locator('#systems').is_visible()
    assert page.locator('body').get_attribute('data-display-mode') == 'basic'
    assert page.locator('#view-title').inner_text() == 'System + Settings'
    issues = visual_issues(page)
    assert not issues['horizontal_overflow'], issues
    assert not issues['clipped_buttons'], issues
    page.screenshot(path=OUTPUT / f'{viewport_name}-systems.png', full_page=True)
    for selector, target in [
        ('[data-more-target="data-health-list"]', '#data-health-list'),
        ('.consumer-more [data-workspace-jump="research-workspace:imports"]', '#upload-result'),
        ('.consumer-more [data-workspace-jump="results-workspace:model"]', '#performance [data-workspace-pane="model"]'),
    ]:
        page.locator('.consumer-more > summary').click()
        page.locator(selector).click()
        assert page.locator(target).first.is_visible()
        assert not page.locator('.consumer-more').evaluate('(element) => element.open')
    page.locator('.consumer-more > summary').click()
    page.keyboard.press("Escape")
    assert not page.locator('.consumer-more').evaluate('(element) => element.open')
    page.locator('button[data-view="best-lines"]:visible').first.click()
    page.locator("#shop-player").fill("Example Player")
    page.locator("#shop-stat").fill("Points")
    page.locator("#shop-sport").select_option("WNBA")
    page.locator('#line-shop-form button[type="submit"]').click()
    page.locator(".best-line-row").first.wait_for()
    assert page.locator(".best-line-row").count() == 2
    assert "Best threshold" in page.locator("#line-shop-result").inner_text()
    issues = visual_issues(page)
    assert not issues["horizontal_overflow"], issues
    assert not issues["clipped_buttons"], issues
    screenshot = OUTPUT / f"{viewport_name}-best-lines.png"
    page.screenshot(path=screenshot, full_page=True)
    page.unroute("**/api/market/best-lines?*")
    return {"viewport": viewport_name, "view": "Best Lines", "screenshot": str(screenshot), **issues}


if __name__ == "__main__":
    raise SystemExit(main())
