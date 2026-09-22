from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from analytics.opportunity_score import locked_opportunity_score, opportunity_score, score_label, score_source_freshness
from web.application.opportunity_presentation import presented_score, scored_opportunities

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def supported_prop():
    return {
        "confidence": 95, "data_quality": {"score": 100},
        "hit_rate": {"sample_size": 30}, "forecast_paid_eligible": True,
        "recommendation_eligibility": {"paid_ready": True, "paper_ready": True},
        "feature_as_of": NOW.isoformat(),
        "decision_receipt": {"market_probability": 80},
    }


@pytest.mark.parametrize(("value", "label"), [
    (0, "Pass"), (59.9, "Pass"), (60, "Marginal"), (69.9, "Marginal"),
    (70, "Watch"), (79.9, "Watch"), (80, "Strong"), (89.9, "Strong"),
    (90, "Elite"), (100, "Elite"),
])
def test_score_labels(value, label):
    assert score_label(value) == label


def test_score_formula_is_deterministic_and_does_not_mutate_forecast():
    prop = supported_prop()
    before = deepcopy(prop)
    result = opportunity_score(prop, now=NOW)
    assert result == opportunity_score(prop, now=NOW)
    assert result["score"] == 98
    assert result["label"] == "Elite"
    assert prop == before
    assert sum(result["weights"].values()) == 1


@pytest.mark.parametrize("change", [
    {"forecast_paid_eligible": False}, {"recommendation_eligibility": {}},
    {"hit_rate": {"sample_size": 19}}, {"hit_rate": {}},
    {"data_quality": {"score": 0}}, {"data_quality": {}},
    {"feature_as_of": None},
    {"feature_as_of": (NOW - timedelta(minutes=31)).isoformat()},
    {"feature_as_of": (NOW + timedelta(minutes=1)).isoformat()},
    {"recommendation_freshness": {"status": "expired"}},
    {"decision_receipt": {"market_probability": 80, "market_consensus": {"stale": True}}},
    {"confidence": float("nan")}, {"confidence": float("inf")}, {"confidence": 101},
])
def test_unsupported_evidence_never_gets_high_score(change):
    result = opportunity_score({**supported_prop(), **change}, now=NOW)
    assert 0 <= result["score"] <= 59
    assert result["restrictions"]


def test_missing_market_does_not_invent_edge():
    result = opportunity_score({**supported_prop(), "decision_receipt": {}}, now=NOW)
    assert result["components"]["market"] == 0
    assert result["score"] < 80
    assert result["missing_evidence"]


def test_risk_penalties_are_bounded_and_reduce_score():
    result = opportunity_score({**supported_prop(), "push_risk": {"score": 200},
                                "correlation_risk_score": 50}, now=NOW)
    assert result["score"] == 83
    assert result["penalties"]["push_risk"] == -10
    assert result["penalties"]["correlation"] == -5


def test_zero_probability_is_not_replaced_with_confidence():
    prop = supported_prop()
    prop["decision_receipt"]["probability"] = 0
    assert opportunity_score(prop, now=NOW)["components"]["model"] == 0


def test_response_presentation_preserves_snapshot_and_actions():
    payload = {"snapshot_id": "locked", "top_opportunities": [supported_prop()]}
    before = deepcopy(payload)
    result = scored_opportunities(payload, "top_opportunities")
    assert payload == before
    assert result["snapshot_id"] == "locked"
    assert result["top_opportunities"][0]["recommendation_eligibility"] == before["top_opportunities"][0]["recommendation_eligibility"]
    assert "edgeiq_score" in result["top_opportunities"][0]


def test_briefing_route_returns_score_without_changing_cached_payload():
    from web.routers.briefing import BriefingDependencies, daily_briefing

    payload = {"top_opportunities": [supported_prop()], "snapshot_id": "snapshot-1"}
    deps = BriefingDependencies(
        briefing=lambda *args: payload, new_scan=lambda *args: {},
        save_scan=lambda *args: {}, run_scan=lambda *args: {}, scan_status=lambda *args: {},
    )
    result = daily_briefing(deps=deps)
    assert result["snapshot_id"] == "snapshot-1"
    assert "edgeiq_score" in result["top_opportunities"][0]
    assert "edgeiq_score" not in payload["top_opportunities"][0]


def test_player_research_score_is_not_applied_to_a_different_line():
    from web.routers.players import PlayerDependencies, player_research

    prop = {**supported_prop(), "line": 18.5}
    payload = {"recommendation": prop, "line": 21.5}
    deps = PlayerDependencies(
        availability=lambda *args: {}, detail=lambda *args: {}, identity=lambda *args: {},
        research=lambda *args: payload, research_evidence=lambda *args: {},
        line_movement=lambda *args: {}, hit_rate=lambda *args: {},
    )
    result = player_research("Player", "Points", line=21.5, deps=deps)
    assert result["edgeiq_score"] is None


def test_locked_score_is_reused_but_never_for_changed_offer_or_model():
    prop = {**supported_prop(), "player": "Player", "stat": "Points", "line": 18.5,
            "model_version": "v1", "recommendation_snapshot_id": "snapshot-1"}
    prop["edgeiq_score"] = locked_opportunity_score(prop, "snapshot-1", NOW)
    assert presented_score(prop) == prop["edgeiq_score"]
    for changed in ({"line": 19.5}, {"model_version": "v2"}, {"confidence": 50},
                    {"recommendation_snapshot_id": "snapshot-2"}):
        assert "snapshot_id" not in presented_score({**prop, **changed})


def test_nested_history_is_not_restamped_as_an_opportunity():
    from services.recommendation_snapshot import stamp_snapshot_payload

    prop = {**supported_prop(), "player": "Player", "stat": "Points", "line": 18.5}
    prop["hit_rate"] = {"player": "Player", "stat": "Points", "line": 18.5, "sample_size": 30}
    payload = {"daily_briefing": {"top_opportunities": [prop]}}
    stamp_snapshot_payload(payload, "snapshot-1", "v1", NOW, updated_sections={"daily_briefing"})
    assert "recommendation_snapshot_id" not in prop["hit_rate"]
    assert presented_score(prop) == prop["edgeiq_score"]


def test_live_freshness_expires_without_rewriting_recorded_score():
    prop = {**supported_prop(), "recommendation_snapshot_id": "snapshot-1"}
    prop["edgeiq_score"] = locked_opportunity_score(prop, "snapshot-1", NOW)
    assert score_source_freshness(prop, now=NOW)["status"] == "fresh"
    assert score_source_freshness(prop, now=NOW + timedelta(minutes=31))["status"] == "expired"
    assert presented_score(prop)["score"] == 98


def test_repository_naive_utc_clock_matches_aware_clock():
    prop = supported_prop()
    assert locked_opportunity_score(prop, "s1", NOW.replace(tzinfo=None)) == locked_opportunity_score(prop, "s1", NOW)
