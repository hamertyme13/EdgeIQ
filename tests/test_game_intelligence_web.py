from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import web.application.game_intelligence_service as game_service
from web.application.game_intelligence_service import game_detail_payload, prop_context_payload, slate_payload
from web.schemas.games import GamePropContextPayload


def test_game_slate_and_detail_use_persisted_snapshots():
    slate = slate_payload("WNBA", refresh=False)
    assert slate["sport"] == "WNBA"
    assert slate["guaranteed"] is False
    if slate["games"]:
        game_id = slate["games"][0]["champion"]["game_id"]
        detail = game_detail_payload(game_id)
        assert detail["game_id"] == game_id
        assert detail["predictions"]


def test_game_slate_shows_schedule_without_inventing_predictions(monkeypatch):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    monkeypatch.setattr(game_service, "latest_slate_predictions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(game_service, "fetch_game_times", lambda *_args: [
        {"game": "Away @ Home", "game_time": f"{today.isoformat()}T19:00:00-04:00"},
    ])

    slate = slate_payload("MLB", refresh=False)

    assert slate["games"] == []
    assert slate["schedule_status"] == "available"
    assert slate["schedule"][0]["game"] == "Away @ Home"


def test_game_slate_reports_schedule_failure_without_claiming_no_games(monkeypatch):
    monkeypatch.setattr(game_service, "latest_slate_predictions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(game_service, "fetch_game_times", lambda *_args: (_ for _ in ()).throw(RuntimeError("upstream unavailable")))

    slate = slate_payload("NFL", refresh=False)

    assert slate["schedule_status"] == "unavailable"
    assert slate["games"] == slate["schedule"] == []


def test_game_slate_merges_other_scheduled_games_without_repeating_prediction(monkeypatch):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    monkeypatch.setattr(game_service, "latest_slate_predictions", lambda *_args, **_kwargs: [
        {"champion": {"game": "New York Yankees @ Boston Red Sox"}},
    ])
    monkeypatch.setattr(game_service, "fetch_game_times", lambda *_args: [
        {"game": "NYY@BOS", "away_team": "New York Yankees", "home_team": "Boston Red Sox",
         "game_time": f"{today.isoformat()}T19:00:00-04:00"},
        {"game": "NYM@PHI", "away_team": "New York Mets", "home_team": "Philadelphia Phillies",
         "game_time": f"{today.isoformat()}T20:00:00-04:00"},
    ])

    slate = slate_payload("MLB", refresh=False)

    assert len(slate["games"]) == 1
    assert [row["game"] for row in slate["schedule"]] == ["NYM@PHI"]


def test_prop_context_api_payload_is_shadow_only():
    context = prop_context_payload(GamePropContextPayload(
        sport="NFL",
        stat="Receiving Yards",
        team="DAL",
        expected_opportunities=8,
        game_prediction={
            "home_team": "DAL", "away_team": "PHI", "expected_margin": -8,
            "expected_total": 47, "blowout_probability": 0.2, "game_script": "away_leading",
        },
    ))
    assert context["shadow_only"] is True
    assert context["confidence_delta"] == 0.0


def test_games_pwa_surface_has_navigation_telemetry_and_mobile_styles():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web/static/index.html").read_text()
    javascript = (root / "web/static/js/games.js").read_text()
    styles = (root / "web/static/styles.css").read_text()
    assert 'data-view="games"' in html
    assert "game_prediction_to_prop" in javascript
    assert "game_context_influenced_prop" in (root / "web/static/app.js").read_text()
    assert "@media (max-width: 640px)" in styles
