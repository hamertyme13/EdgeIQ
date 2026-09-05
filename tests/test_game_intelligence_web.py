from pathlib import Path

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
