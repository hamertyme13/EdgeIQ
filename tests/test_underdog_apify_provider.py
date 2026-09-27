from datetime import UTC, datetime, timedelta

from data.providers import underdog_apify


def _offer(**changes):
    row = {
        "projection_id": "offer-1", "line": 2.5, "stat": "hits_runs_rbis",
        "status": "active", "is_live": False, "player_name": "Shohei Ohtani",
        "player_team": "LAD", "league": "MLB",
        "game_start": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        "game_status": "scheduled", "season_type": "regular",
        "home_team": "SF", "away_team": "LAD", "line_type": "balanced",
        "higher_payout_multiplier": "1.11", "lower_payout_multiplier": "0.84",
    }
    row.update(changes)
    return row


def test_normalizes_standard_offer_without_claiming_payout_verification():
    prop = underdog_apify.normalize_offer(_offer(), "2026-09-26T00:00:00+00:00")
    assert prop is not None
    assert prop["player"] == "Shohei Ohtani"
    assert prop["game"] == "LAD @ SF"
    assert prop["payout_evidence"] == "unverified"
    assert prop["under_multiplier"] == "0.84"


def test_rejects_live_adjusted_past_and_incomplete_offers():
    for change in (
        {"is_live": True}, {"status": "suspended"},
        {"game_status": "in_progress"}, {"line_type": "goblin"},
        {"home_team": ""}, {"projection_id": ""},
        {"game_start": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    ):
        assert underdog_apify.normalize_offer(_offer(**change), "now") is None


def test_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.delenv("EDGEIQ_UNDERDOG_APIFY_ENABLED", raising=False)
    assert not underdog_apify.configured()
    assert underdog_apify.fetch_projections() == []


def test_fresh_cache_avoids_paid_run(monkeypatch, tmp_path):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.setenv("EDGEIQ_UNDERDOG_APIFY_ENABLED", "1")
    monkeypatch.setattr(underdog_apify, "CACHE_PATH", tmp_path / "underdog.json")
    underdog_apify._write_cache([{"player": "Cached"}])
    monkeypatch.setattr(underdog_apify.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    assert underdog_apify.fetch_projections() == [{"player": "Cached"}]
