from datetime import UTC, datetime, timedelta

import pytest

import web.app as app
from data.providers.generic_props import normalize_props
from web.schemas.entries import EntryPayload, PropPayload


@pytest.fixture
def offer_case(monkeypatch):
    now = datetime.now(UTC)
    prop = PropPayload(
        player="Test Player", sport="WNBA", stat="Points", line=10.5,
        direction="Over", platform="PrizePicks", provider_offer_id="offer-1",
        provider_event_id="event-1", game="SEA @ LV",
        game_time=(now + timedelta(hours=2)).isoformat(), feature_as_of=now.isoformat(),
    )
    row = {**prop.model_dump(), "provider_offer_verified_at": now.isoformat()}
    rows = [row]
    monkeypatch.setattr(app, "_matching_market_props", lambda *args: rows)
    monkeypatch.setattr(app, "_handoff_leg", lambda *args: {})
    return EntryPayload(props=[prop]), rows


def verify(case):
    return app._verify_handoff_live_offers(case[0], "PrizePicks")


def test_fresh_exact_offer_passes(offer_case):
    assert verify(offer_case)["all_current"] is True


@pytest.mark.parametrize("changes", [
    {"provider_offer_verified_at": ""},
    {"stale": True},
    {"provider_event_id": "different-event"},
    {"game_time": "2020-01-01T00:00:00+00:00"},
    {"allowed_directions": ["Under"]},
    {"provider_offer_id": "different-offer"},
    {"line": None},
])
def test_unverified_or_mismatched_offer_blocks(offer_case, changes):
    offer_case[1][0].update(changes)
    result = verify(offer_case)
    assert result["all_current"] is False
    assert result["legs"][0]["blocking_reason"]


def test_changed_zero_line_is_not_replaced_with_requested_line(offer_case):
    offer_case[1][0]["line"] = 0
    result = verify(offer_case)
    assert result["changed"] == 1
    assert result["legs"][0]["current_line"] == 0
    assert "now 0" in result["legs"][0]["blocking_reason"]


def test_exact_requested_identity_wins_over_same_line_duplicate(offer_case):
    rows = offer_case[1]
    rows.insert(0, {**rows[0], "provider_offer_id": "another-offer"})
    result = verify(offer_case)
    assert result["all_current"] is True
    assert result["legs"][0]["provider_offer_id"] == "offer-1"


@pytest.mark.parametrize("line", [None, "", "unavailable", "NaN", "Infinity", float("-inf"), True, []])
def test_malformed_line_blocks_without_crashing(offer_case, line):
    offer_case[1][0]["line"] = line
    result = verify(offer_case)
    assert result["all_current"] is False
    assert result["unavailable"] == 1
    assert result["legs"][0]["current_line"] is None


def test_malformed_candidate_does_not_hide_valid_offer(offer_case):
    rows = offer_case[1]
    rows.insert(0, {**rows[0], "line": "unavailable"})
    assert verify(offer_case)["all_current"] is True
    assert rows[0]["line"] == "unavailable"


def test_configured_feed_restriction_blocks_handoff(offer_case):
    original = offer_case[1][0]
    normalized = normalize_props([{**original, "allowed_directions": ["Under"]}], "PrizePicks")[0]
    offer_case[1][0] = {**original, **normalized}
    assert verify(offer_case)["unavailable"] == 1
