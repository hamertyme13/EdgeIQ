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
    monkeypatch.setattr(app, "_matching_market_props", lambda *args, **kwargs: (
        kwargs["source_props"] if kwargs.get("source_props") is not None else rows
    ))
    monkeypatch.setattr(app, "_handoff_leg", lambda *args, **kwargs: {})
    return EntryPayload(props=[prop]), rows


def verify(case):
    return app._verify_handoff_live_offers(case[0], "PrizePicks")


def test_fresh_exact_offer_passes(offer_case):
    assert verify(offer_case)["all_current"] is True


def test_handoff_verification_reuses_supplied_board_without_fetch(offer_case, monkeypatch):
    monkeypatch.setattr(app, "_fetch_props", lambda *args: pytest.fail("handoff re-fetched provider board"))
    result = app._verify_handoff_live_offers(
        offer_case[0], "PrizePicks", source_props_by_sport={"WNBA": offer_case[1]},
    )
    assert result["all_current"] is True


def test_handoff_reuses_one_board_for_value_and_offer_checks_after_analysis(offer_case, monkeypatch):
    payload, rows = offer_case
    payload.props.append(payload.props[0].model_copy(update={
        "player": "Second Player", "provider_offer_id": "offer-2",
    }))
    rows.append({**rows[0], "player": "Second Player", "provider_offer_id": "offer-2"})
    calls = []
    monkeypatch.setattr(app, "_fetch_props", lambda platform, sport: calls.append((platform, sport)) or rows)
    monkeypatch.setattr(app, "_entry_from_payload", lambda value: None)
    monkeypatch.setattr(app, "_entry_analysis", lambda *args: {"risk_guardrails": [], "release_verdict": {"paid_allowed": True}})
    monkeypatch.setattr(app, "_platform_value_check", lambda *args, **kwargs: {
        "recommended_platform": "PrizePicks", "payout_verified": True,
    })
    monkeypatch.setattr(app, "_handoff_copy_text", lambda *args: "Slip")
    result = app._entry_handoff_payload(payload)
    assert calls == [("Both", "WNBA")]
    assert result["live_verification"]["current"] == 2
    assert result["live_verification"]["all_current"] is True


def test_recent_offer_for_started_game_cannot_be_handed_off(offer_case):
    started = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    offer_case[0].props[0].game_time = started
    offer_case[1][0]["game_time"] = started
    result = verify(offer_case)
    assert result["all_current"] is False
    assert result["legs"][0]["game_started"] is True
    assert "game has started" in result["legs"][0]["blocking_reason"]


@pytest.mark.parametrize("missing_side", ["saved", "provider"])
def test_verified_offer_without_both_start_times_cannot_be_handed_off(offer_case, missing_side):
    if missing_side == "saved":
        offer_case[0].props[0].game_time = ""
    else:
        offer_case[1][0]["game_time"] = "invalid"
    result = verify(offer_case)
    assert result["all_current"] is False
    assert result["legs"][0]["game_start_status"] == "unavailable"
    assert "start time is unavailable" in result["legs"][0]["blocking_reason"]


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


def test_other_book_offer_uses_its_own_verified_identity(offer_case):
    payload, rows = offer_case
    rows[0]["platform"] = "Underdog"
    rows[0]["provider_offer_id"] = "underdog-offer-1"
    result = app._verify_handoff_live_offers(payload, "Underdog")
    assert result["all_current"] is True
    assert result["legs"][0]["provider_offer_id"] == "underdog-offer-1"


def test_other_book_still_needs_a_provider_offer_id(offer_case):
    payload, rows = offer_case
    rows[0]["platform"] = "Underdog"
    rows[0]["provider_offer_id"] = ""
    result = app._verify_handoff_live_offers(payload, "Underdog")
    assert result["all_current"] is False
    assert "offer ID is missing" in result["legs"][0]["blocking_reason"]


@pytest.mark.parametrize("change", [{"line": 11.5}, {"provider_event_id": "other-event"},
                                    {"allowed_directions": ["Under"]}])
def test_other_book_does_not_accept_changed_market(offer_case, change):
    payload, rows = offer_case
    rows[0].update({"platform": "Underdog", "provider_offer_id": "underdog-offer-1", **change})
    result = app._verify_handoff_live_offers(payload, "Underdog")
    assert result["all_current"] is False
    assert result["legs"][0]["blocking_reason"]


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
