from datetime import UTC, datetime, timedelta

from services.offer_snapshot import offer_fingerprint
from web.application.generator_card_review import link_current_offer_snapshots


def _prop() -> dict:
    return {
        "platform": "PrizePicks", "player": "Test Player", "sport": "NBA", "stat": "Points",
        "line": 25.5, "standard_line": 25.5, "game": "AAA @ BBB",
        "game_time": "2026-11-03T00:30:00+00:00", "provider_offer_id": "offer-1",
    }


def test_generator_links_only_current_exact_offer() -> None:
    now = datetime(2026, 11, 2, 20, tzinfo=UTC)
    prop = _prop()
    fingerprint = offer_fingerprint(prop)
    snapshot = {
        "last_observed_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=4)).isoformat(),
        "game_start": prop["game_time"],
    }

    assert link_current_offer_snapshots([prop], lambda key: snapshot if key == fingerprint else None, now=now) == 1
    assert prop["offer_snapshot_id"] == fingerprint

    snapshot["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    assert link_current_offer_snapshots([prop], lambda _key: snapshot, now=now) == 0
    assert prop["offer_snapshot_id"] == ""
