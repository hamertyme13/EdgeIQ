from web.application.recommendation_policy import recommendation_eligibility


def _verified_prop() -> dict:
    return {
        "stat": "Points",
        "line": 19.5,
        "confidence": 63.0,
        "market_supported": True,
        "end_to_end_confirmed": True,
        "provider_backed": True,
        "forecast_paid_eligible": True,
        "provider_event_id": "event-20260827-001",
        "provider_offer_id": "offer-001",
        "recommendation_freshness": {"status": "fresh"},
        "decision_receipt": {"market_probability": 57.0},
    }


def test_verified_recommendation_can_be_paid_ready() -> None:
    result = recommendation_eligibility(_verified_prop(), trust_score=72.0, model_paid_enabled=True)

    assert result["paper_ready"] is True
    assert result["paid_ready"] is True
    assert result["label"] == "Paid-ready"


def test_auto_projection_is_paper_only() -> None:
    prop = {**_verified_prop(), "provider_backed": False}

    result = recommendation_eligibility(prop, trust_score=72.0, model_paid_enabled=True)

    assert result["paper_ready"] is True
    assert result["paid_ready"] is False
    assert result["label"] == "Paper only"
    assert any("auto-generated" in reason for reason in result["paid_blocks"])


def test_unsettleable_or_expired_prop_is_research_only() -> None:
    prop = {
        **_verified_prop(),
        "end_to_end_confirmed": False,
        "recommendation_freshness": {"status": "expired"},
    }

    result = recommendation_eligibility(prop, trust_score=72.0, model_paid_enabled=True)

    assert result["paper_ready"] is False
    assert result["paid_ready"] is False
    assert result["label"] == "Research only"
    assert len(result["paper_blocks"]) == 2


def test_model_release_gate_prevents_paid_label() -> None:
    result = recommendation_eligibility(_verified_prop(), trust_score=72.0, model_paid_enabled=False)

    assert result["paper_ready"] is True
    assert result["paid_ready"] is False
    assert any("model release" in reason for reason in result["paid_blocks"])


def test_missing_exact_provider_identity_prevents_paid_label() -> None:
    prop = {**_verified_prop(), "provider_event_id": "", "provider_offer_id": ""}

    result = recommendation_eligibility(prop, trust_score=72.0, model_paid_enabled=True)

    assert result["paper_ready"] is True
    assert result["paid_ready"] is False
    assert any("event ID" in reason for reason in result["paid_blocks"])
    assert any("offer ID" in reason for reason in result["paid_blocks"])
