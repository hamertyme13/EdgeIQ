import json
from datetime import UTC, datetime

import web.application.briefing_service as briefing_service
from web.application.briefing_service import cached_daily_briefing_payload
from web.application.slate_changes import compare_briefings


NOW = "2026-10-07T16:00:00Z"
BEFORE = "2026-10-07T15:00:00Z"


def _prop(**changes):
    return {
        "player": "Azurá Stevens", "sport": "WNBA", "platform": "PrizePicks",
        "stat": "Points", "direction": "Over", "game": "Storm @ Aces",
        "game_time": "2026-10-07T23:00:00Z", "line": 18.5,
        "projection": 21.0, "confidence": 61.0, "score": 70,
        "edgeiq_score": {"label": "Watch"},
        "risk_profile": {"key": "balanced"},
        "recommendation_eligibility": {"paper_ready": True, "paid_ready": False},
        "actionable": True,
        **changes,
    }


def test_slate_changes_uses_canonical_identity_and_tracks_observed_fields():
    previous = {"as_of": BEFORE, "games_today": [
        {"sport": "WNBA", "game": "Storm @ Aces", "injuries": "No confirmed injuries"},
    ], "top_opportunities": [_prop()]}
    current = {"as_of": NOW, "games_today": [
        {"sport": "WNBA", "game": "Aces @ Storm", "injuries": "One starter questionable"},
    ], "top_opportunities": [_prop(
        player="Azura Stevens", game="Aces @ Storm", line=19.5,
        projection=20.5, confidence=64.0, edgeiq_score={"label": "Strong"},
        recommendation_eligibility={"paper_ready": True, "paid_ready": True},
    )]}
    result = compare_briefings(previous, current, previous_at=BEFORE, current_at=NOW)
    assert result["available"] is True
    assert result["counts"]["new_games"] == 0
    assert result["counts"]["removed_games"] == 0
    assert result["counts"]["new_recommendations"] == 0
    assert result["counts"]["line_changes"] == 1
    assert result["counts"]["projection_changes"] == 1
    assert result["counts"]["confidence_changes"] == 1
    assert result["counts"]["injury_context_changes"] == 1
    assert result["counts"]["upgrades"] == 1
    assert result["counts"]["invalidated"] == 0


def test_slate_changes_distinguishes_removed_from_invalidated():
    previous = {"as_of": BEFORE, "top_opportunities": [_prop(), _prop(player="Other Player", stat="Rebounds")], "games_today": []}
    current = {"as_of": NOW, "top_opportunities": [_prop(actionable=False)], "games_today": []}
    result = compare_briefings(previous, current, previous_at=BEFORE, current_at=NOW)
    assert result["counts"]["removed_recommendations"] == 1
    assert result["counts"]["invalidated"] == 1


def test_slate_changes_requires_prior_same_day_snapshot():
    current = {"as_of": NOW, "top_opportunities": [], "games_today": []}
    assert compare_briefings(None, current)["available"] is False
    previous = {**current, "as_of": "2026-10-06T16:00:00Z"}
    result = compare_briefings(previous, current, previous_at=previous["as_of"], current_at=NOW)
    assert result["available"] is False
    assert "another day" in result["message"]


def test_refresh_persists_comparison_for_fast_cached_reads(monkeypatch):
    monkeypatch.setattr(briefing_service, "utc_now", lambda: datetime(2026, 10, 7, 16, tzinfo=UTC))
    store = {}
    runs = {"count": 0}

    def build(platform, sport):
        runs["count"] += 1
        return {"as_of": NOW, "platform": platform, "sport": sport,
                "games_today": [], "top_opportunities": [_prop(line=18.5 + runs["count"])]}

    options = {
        "cache_version": 15, "ttl_hours": 10,
        "get_setting": lambda key, default="": store.get(key, default),
        "set_setting": lambda key, value: store.__setitem__(key, value),
        "safe_json_loads": lambda value: json.loads(value) if value else {},
        "build_payload": build,
        "refresh_runtime_state": lambda payload: payload,
        "build_placeholder": lambda *_args: {},
    }
    first = cached_daily_briefing_payload("PrizePicks", "WNBA", refresh=True, cached_only=False, **options)
    second = cached_daily_briefing_payload("PrizePicks", "WNBA", refresh=True, cached_only=False, **options)
    cached = cached_daily_briefing_payload("PrizePicks", "WNBA", refresh=False, cached_only=True, **options)
    assert first["slate_changes"]["available"] is False
    assert second["slate_changes"]["counts"]["line_changes"] == 1
    assert cached["slate_changes"] == second["slate_changes"]
    assert runs["count"] == 2
