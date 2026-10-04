from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
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
                if os.environ.get("EDGEIQ_VISUAL_FOCUS") == "timeline":
                    results.append(capture_market_model_timeline(page, viewport_name))
                    page.close()
                    continue
                for view_name in VIEWS:
                    results.append(capture_view(page, viewport_name, view_name))
                results.extend(capture_research_details(page, viewport_name))
                results.append(capture_entry_summary(page, viewport_name))
                results.append(capture_model_track_record(page, viewport_name))
                results.append(capture_best_lines(page, viewport_name))
                results.append(capture_recommendation_compare(page, viewport_name))
                results.append(capture_market_disagreement(page, viewport_name))
                results.append(capture_market_model_timeline(page, viewport_name))
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


def capture_market_model_timeline(page: Page, viewport_name: str) -> dict:
    page.evaluate("""() => {
      const drawer = document.createElement('section');
      drawer.id = 'timeline-visual-fixture';
      drawer.className = 'analysis-card';
      drawer.style.maxWidth = '600px';
      drawer.innerHTML = renderMarketModelTimeline({
        summary: 'Two saved recommendation states.', clv: null,
        events: [
          {created_at: '2026-10-03T12:00:00Z', platform: 'PrizePicks', model_version: 'v2.4',
           changes: ['recommendation_created'], line: 23.5, projection: 26.1,
           model_probability: 67, calibrated_probability: 64},
          {created_at: '2026-10-03T13:00:00Z', platform: 'PrizePicks', model_version: 'v2.4',
           changes: ['provider_line_change', 'model_projection_change'], line: 24.5,
           projection: 27, model_probability: 69, calibrated_probability: 65},
        ],
      });
      document.querySelector('#drawer-content').prepend(drawer);
      document.querySelector('#recommendation-drawer').hidden = false;
    }""")
    fixture = page.locator('#timeline-visual-fixture')
    assert fixture.locator('polyline').count() == 2
    assert 'No exact closing line' in fixture.inner_text()
    issues = visual_issues(page)
    assert not issues['horizontal_overflow'], issues
    assert not issues['clipped_buttons'], issues
    screenshot = OUTPUT / f'{viewport_name}-market-model-timeline.png'
    page.locator('#recommendation-drawer .drawer-panel').screenshot(path=screenshot)
    page.evaluate("document.querySelector('#recommendation-drawer').hidden = true")
    fixture.evaluate('(element) => element.remove()')
    return {'viewport': viewport_name, 'view': 'Market model timeline', 'screenshot': str(screenshot), **issues}


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


def capture_recommendation_compare(page: Page, viewport_name: str) -> dict:
    page.route("**/api/analytics/model-track-record?*", lambda route: route.fulfill(json={
        "truncated": False,
        "versions": [{"model_version": "v2.4", "platform": "PrizePicks", "direction": "Over",
                      "settled_predictions": 30, "actual_hit_rate": 56.7}],
    }))
    page.evaluate("""() => {
      setView('dashboard');
      const rows = [
        {player:'Example One',sport:'WNBA',platform:'PrizePicks',stat:'Points',direction:'Over',line:19.5,
         projection:22,confidence:64,score:70,model_version:'v2.4',risk_profile:{key:'balanced',label:'Balanced'},
         edgeiq_score:{score:72},calibration_presentation:{model_probability:68,calibrated_probability:63,
         segment_sample_size:120,label:'Calibrated'},counterargument:{fragility_label:'Low',fragility_score:20},
         recommendation_freshness:{status:'fresh'},recommendation_eligibility:{paper_ready:true}},
        {player:'Example Two',sport:'WNBA',platform:'Underdog',stat:'Rebounds',direction:'Under',line:8.5,
         projection:7,confidence:61,score:66,model_version:'v2.4',risk_profile:{key:'balanced',label:'Balanced'},
         edgeiq_score:{score:79},calibration_presentation:{model_probability:65,calibrated_probability:60,
         segment_sample_size:105,label:'Calibrated'},counterargument:{fragility_label:'Moderate',fragility_score:35},
         recommendation_freshness:{status:'fresh'},recommendation_eligibility:{paper_ready:true}}
      ];
      const data = {sport:'WNBA',platform:'Both',top_opportunities:rows,summary:{confirmed_props:2},
        sections:{bet:[],paper:[],watch:[],avoid:[]},games_today:[],cache:{hit:true},user:{greeting:'Good morning.'}};
      state.dailyBriefing = data;
      renderDailyBriefing(data);
      document.querySelector('.briefing-explore-drawer').open = true;
    }""")
    buttons = page.locator("[data-compare-opportunity]")
    assert buttons.count() == 2
    buttons.nth(0).click()
    buttons.nth(1).click()
    page.locator("#compare-selected-opportunities").click()
    page.locator(".recommendation-compare-table").wait_for()
    output_text = page.locator("#recommendation-compare-output").inner_text()
    assert "example one" in output_text.lower(), output_text
    assert "example two" in output_text.lower(), output_text
    page.locator("#recommendation-compare-metric").select_option("score")
    assert "Highest EdgeIQ Score" in page.locator("#recommendation-compare-output").inner_text()
    issues = visual_issues(page)
    assert not issues["horizontal_overflow"], issues
    assert not issues["clipped_buttons"], issues
    screenshot = OUTPUT / f"{viewport_name}-recommendation-compare.png"
    page.screenshot(path=screenshot, full_page=True)
    page.unroute("**/api/analytics/model-track-record?*")
    return {"viewport": viewport_name, "view": "Recommendation comparison", "screenshot": str(screenshot), **issues}


def capture_market_disagreement(page: Page, viewport_name: str) -> dict:
    page.route("**/api/analytics/market-disagreement?*", lambda route: route.fulfill(json={
        "message": "1 exact-line no-vig comparison from the cached briefing.",
        "note": "A difference is not expected value or a profit estimate.",
        "rows": [{"player": "Example One", "direction": "Over", "line": 19.5, "stat": "Points",
                  "platform": "PrizePicks", "sport": "WNBA", "model_probability": 61,
                  "market_probability": 54, "raw_difference": 7, "calibrated_probability": 58,
                  "effective_difference": 4, "calibration_samples": 120,
                  "calibration_uncertainty_points": 3, "within_calibration_uncertainty": False,
                  "market_book_count": 2,
                  "market_timestamp_coverage": 2, "context": "Multi-book comparison; model uncertainty still applies"}],
    }))
    page.locator("#market-disagreement-panel summary").click()
    page.locator(".market-disagreement-row").wait_for()
    content = page.locator("#market-disagreement-output").inner_text()
    assert "+7.0 pts" in content
    assert "+4.0 pts" in content
    issues = visual_issues(page)
    assert not issues["horizontal_overflow"], issues
    assert not issues["clipped_buttons"], issues
    screenshot = OUTPUT / f"{viewport_name}-market-disagreement.png"
    page.screenshot(path=screenshot, full_page=True)
    page.unroute("**/api/analytics/market-disagreement?*")
    return {"viewport": viewport_name, "view": "Market disagreement", "screenshot": str(screenshot), **issues}


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

    game_time = (datetime.now(UTC) + timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
    offer = {"sport": "WNBA", "stat": "Points", "game": "Example A @ Example B",
             "game_time": game_time.isoformat().replace("+00:00", "Z"), "line_offer_type": "standard"}
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
        target_locator = page.locator(target).first
        visible = target_locator.is_visible()
        if target == '#data-health-list' and not visible:
            visible = target_locator.locator('..').is_visible()
        assert visible, f"{selector} did not reveal {target}"
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
    page.locator('[data-best-provider]').select_option('Underdog')
    assert page.locator('.best-line-row:visible').count() == 1
    assert 'Underdog' in page.locator('.best-line-row:visible').inner_text()
    page.locator('[data-best-provider]').select_option('')
    assert page.locator('.best-line-row:visible').count() == 2
    assert "Best threshold" in page.locator("#line-shop-result").inner_text()
    issues = visual_issues(page)
    assert not issues["horizontal_overflow"], issues
    assert not issues["clipped_buttons"], issues
    screenshot = OUTPUT / f"{viewport_name}-best-lines.png"
    page.screenshot(path=screenshot, full_page=True)
    page.unroute("**/api/market/best-lines?*")
    page.evaluate('state.entryProps = []')
    page.locator('[data-add-best-line="0"]').click()
    assert page.locator('#entries').is_visible()
    transferred = page.evaluate('state.entryProps[0]')
    assert transferred['player'] == 'Example Player'
    assert transferred['line'] == 20.5
    assert transferred['platform'] == 'PrizePicks'
    assert transferred['direction'] == 'Over'
    page.evaluate('setView("best-lines")')
    page.locator('[data-add-best-line="1"]').click()
    assert page.evaluate('state.entryProps.length') == 1
    assert 'separate' in page.locator('#entry-status').inner_text()
    page.evaluate('''() => {
        state.lastAnalysis = {score: 90};
        state.lastEntryPayload = {old: true};
        document.getElementById('place-entry').disabled = false;
        loadPaperProps([{player:'Restricted Example', platform:'Sleeper', sport:'WNBA',
            stat:'Points', line:20.5, direction:'Over', allowed_directions:['Under']}]);
    }''')
    assert page.evaluate('state.lastAnalysis === null && state.lastEntryPayload === null')
    assert page.locator('#place-entry').is_disabled()
    assert page.evaluate('state.entryProps[0].direction') == 'Over'
    assert 'Direction unavailable' in page.locator('#entry-props').inner_text()
    page.locator('[data-edit-prop="0"]').click()
    assert page.locator('[data-edit-field="direction"] option', has_text='Over').get_attribute('disabled') is not None
    page.locator('[data-edit-field="direction"]').select_option(label='Under')
    page.locator('[data-save-prop="0"]').click()
    assert page.evaluate('state.entryProps[0].direction') == 'Under'
    assert 'Direction unavailable' not in page.locator('#entry-props').inner_text()
    page.screenshot(path=OUTPUT / f'{viewport_name}-entry-direction-review.png', full_page=True)
    from urllib.parse import parse_qs, urlparse

    requests = []

    def batch_response(route):
        player = parse_qs(urlparse(route.request.url).query)['player'][0]
        assert parse_qs(urlparse(route.request.url).query)['stat'][0] == 'Points'
        requests.append(player)
        if player == 'Another Player' and requests.count(player) == 1:
            route.fulfill(json={**payload, 'player': player, 'lines': []})
            return
        route.fulfill(json={**payload, 'player': player,
                           'lines': [{**row, 'player': player} for row in payload['lines']]})

    page.route('**/api/market/best-lines?*', batch_response)
    page.evaluate('setView("best-lines")')
    page.locator('#shop-player').fill('Example Player, Another Player, example player')
    page.locator('#line-shop-form button[type="submit"]').click()
    page.locator('[data-retry-best-lines]').wait_for()
    assert page.locator('.best-line-row').count() == 2
    page.locator('#shop-stat').fill('Assists')
    page.locator('[data-retry-best-lines]').click()
    page.wait_for_function("document.querySelectorAll('.best-line-row').length === 4")
    page.wait_for_function("document.querySelector('#line-shop-result').getAttribute('aria-busy') === 'false'")
    assert 'Another Player' in page.locator('#line-shop-result').inner_text()
    assert requests.count('Another Player') == 2
    assert requests.count('example player') == 1
    page.unroute('**/api/market/best-lines?*')
    requests.clear()
    stalled_routes = []

    def stopped_response(route):
        player = parse_qs(urlparse(route.request.url).query)['player'][0]
        requests.append(player)
        if player == 'Slow Player' and requests.count(player) == 1:
            stalled_routes.append(route)
            return
        route.fulfill(json={**payload, 'player': player,
                           'lines': [{**row, 'player': player} for row in payload['lines']]})

    page.route('**/api/market/best-lines?*', stopped_response)
    page.locator('#shop-stat').fill('Points')
    page.locator('#shop-player').fill('Fast Player, Slow Player')
    page.locator('#line-shop-form button[type="submit"]').click()
    page.wait_for_function("document.querySelector('#best-lines-progress')?.textContent.includes('Slow Player')")
    assert page.locator('.best-line-row').count() == 2
    page.get_by_role('button', name='Stop comparison', exact=True).click()
    page.locator('[data-retry-best-lines]').wait_for()
    assert page.locator('.best-line-row').count() == 2
    assert 'stopped' in page.locator('#best-lines-progress').inner_text()
    for route in stalled_routes:
        route.abort()
    page.locator('[data-retry-best-lines]').click()
    page.wait_for_function("document.querySelectorAll('.best-line-row').length === 4")
    page.wait_for_function("document.querySelector('#line-shop-result').getAttribute('aria-busy') === 'false'")
    assert requests.count('Fast Player') == 1
    assert requests.count('Slow Player') == 2
    page.unroute('**/api/market/best-lines?*')
    return {"viewport": viewport_name, "view": "Best Lines", "screenshot": str(screenshot), **issues}


if __name__ == "__main__":
    raise SystemExit(main())
