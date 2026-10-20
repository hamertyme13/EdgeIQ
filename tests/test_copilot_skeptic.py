from datetime import UTC, datetime, timedelta

from web.application import copilot_service
from web.application.copilot_skeptic import skeptic_response
from web.schemas import CopilotQueryPayload

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
ROW = {
    "player": "Example Player", "sport": "WNBA", "stat": "Points",
    "direction": "Under", "line": 19.5, "platform": "PrizePicks", "game": "DAL vs MIN",
    "counterargument": {
        "risk_factors": ["Minutes may increase with a lineup change.", "Opponent pace may rise."],
        "invalidating_conditions": ["A verified starter change raises expected minutes."],
        "fragility_label": "Moderate",
    },
    "calibration_presentation": {"status": "PARTIAL", "segment_sample_size": 12},
    "recommendation_freshness": {"status": "fresh"},
    "recommendation_eligibility": {"paid_ready": False},
}


def _payload(**updates):
    return CopilotQueryPayload(
        question="Challenge this recommendation", platform="PrizePicks", sport="WNBA",
        selected_snapshot_id="snapshot-1", selected_recommendation_index=0,
        selected_recommendation_identity={
            key: str(ROW.get(key) or "")
            for key in ("player", "sport", "stat", "direction", "line", "platform", "game")
        },
        **updates,
    )


def _briefing(**updates):
    return {
        "recommendation_snapshot_id": "snapshot-1",
        "as_of": (NOW - timedelta(minutes=2)).isoformat(),
        "top_opportunities": [ROW],
        **updates,
    }


def test_skeptic_uses_recorded_risks_without_model_call():
    result = skeptic_response(_payload(), lambda *_args: _briefing(), now=NOW)
    assert result["grounded"] is True
    assert result["provider"] == "EdgeIQ Local"
    assert "Minutes may increase" in result["response"]["answer"]
    assert result["response"]["supporting_evidence"] == ["Opponent pace may rise."]
    assert result["invalidating_conditions"] == ["A verified starter change raises expected minutes."]
    assert "calibrated" in result["response"]["missing_information"][0]


def test_skeptic_rejects_changed_snapshot_and_row():
    changed_snapshot = skeptic_response(_payload(), lambda *_args: _briefing(recommendation_snapshot_id="new"), now=NOW)
    changed_row = skeptic_response(
        _payload(), lambda *_args: _briefing(top_opportunities=[{**ROW, "line": 20.5}]), now=NOW,
    )
    assert changed_snapshot["grounded"] is False
    assert changed_row["grounded"] is False


def test_skeptic_rejects_stale_or_expired_evidence():
    stale = skeptic_response(_payload(), lambda *_args: _briefing(as_of=(NOW - timedelta(hours=1)).isoformat()), now=NOW)
    expired = skeptic_response(
        _payload(), lambda *_args: _briefing(top_opportunities=[{
            **ROW, "recommendation_freshness": {"status": "expired"},
        }]), now=NOW,
    )
    assert stale["grounded"] is False
    assert expired["grounded"] is False


def test_copilot_routes_challenge_without_ollama(monkeypatch):
    monkeypatch.setattr(copilot_service, "ollama_structured", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Ollama called")))
    # The integration path uses the real clock, so the fixture has a live timestamp.
    result = copilot_service.copilot_query_payload(
        _payload(),
        player_research=lambda *_args: {}, loss_review=lambda: {},
        briefing=lambda *_args: _briefing(as_of=datetime.now(UTC).isoformat()),
        portfolio=lambda: {},
    )
    assert result["intent"] == "skeptic"
    assert result["grounded"] is True
