from datetime import UTC, datetime, timedelta

from data.providers import sleeper_apify


def _offer(**changes):
    row = {
        "platform": "sleeper", "projection_id": "line-1", "line": 57.5,
        "stat": "receiving_yards", "status": "active", "is_live": False,
        "in_game": False, "is_alternate": False,
        "player_name": "Dalton Kincaid", "player_team": "BUF", "league": "NFL",
        "game_start": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "game_status": "pre_game", "home_team": "BUF", "away_team": "LAC",
        "game_id": "game-1", "over_line_id": "over-1", "under_line_id": "under-1",
        "over_multiplier": 1.78, "under_multiplier": 1.78,
        "season_type": "regular",
    }
    row.update(changes)
    return row


def test_normalize_actor_offer_preserves_identity_and_unverified_payout():
    prop = sleeper_apify.normalize_offer(_offer(), "2026-09-26T00:00:00+00:00")
    assert prop is not None
    assert prop["stat"] == "Receiving Yards"
    assert prop["game"] == "LAC @ BUF"
    assert prop["under_line_id"] == "under-1"
    assert prop["payout_evidence"] == "unverified"


def test_rejects_non_pregame_alternate_and_incomplete_rows():
    for change in (
        {"is_live": True}, {"in_game": True}, {"is_alternate": True},
        {"status": "suspended"}, {"game_status": "in_progress"},
        {"game_id": None}, {"home_team": None},
        {"game_start": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
        {"season_type": "season_long"},
    ):
        assert sleeper_apify.normalize_offer(_offer(**change), "now") is None


def test_actor_is_disabled_without_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.delenv("EDGEIQ_SLEEPER_APIFY_ENABLED", raising=False)
    assert not sleeper_apify.configured()
    assert sleeper_apify.fetch_projections() == []


def test_fresh_cache_avoids_billable_run(monkeypatch, tmp_path):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.setenv("EDGEIQ_SLEEPER_APIFY_ENABLED", "1")
    monkeypatch.setattr(sleeper_apify, "CACHE_PATH", tmp_path / "sleeper.json")
    sleeper_apify._write_cache([{"player": "Cached"}])
    monkeypatch.setattr(sleeper_apify.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    assert sleeper_apify.fetch_projections() == [{"player": "Cached"}]
