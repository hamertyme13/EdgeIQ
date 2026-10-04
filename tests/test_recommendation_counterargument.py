from analytics.recommendation_counterargument import counterargument


def _strong_prop() -> dict:
    return {
        "line": 20.5,
        "projection": 25.0,
        "forecast_snapshot": {"effective_sample_size": 40, "standard_deviation": 4.0, "features": {}},
        "data_quality": {"score": 85},
        "recommendation_freshness": {"status": "fresh"},
        "recommendation_eligibility": {"paid_blocks": []},
        "decision_receipt": {"probability": 64, "market_probability": 57, "portfolio_exposure": {}},
    }


def test_strong_evidence_has_low_fragility_without_changing_probability():
    prop = _strong_prop()
    result = counterargument(prop)
    assert result["fragility_label"] == "Low"
    assert result["fragility_score"] == 0
    assert result["supporting_factors"]
    assert prop["decision_receipt"]["probability"] == 64


def test_missing_evidence_is_not_presented_as_low_fragility():
    result = counterargument({"line": 20.5, "recommendation_freshness": {"status": "unknown"}})
    assert result["fragility_label"] == "High"
    assert result["uncertainty_score"] >= 45
    assert any("unavailable" in reason.lower() for reason in result["risk_factors"])


def test_stale_offer_role_uncertainty_and_overlap_raise_fragility():
    prop = _strong_prop()
    prop["forecast_snapshot"]["features"] = {
        "role_evidence_required": True, "role_evidence_verified": False,
    }
    prop["recommendation_freshness"] = {"status": "expired"}
    prop["decision_receipt"]["portfolio_exposure"] = {"same_market_entries": 2}
    result = counterargument(prop)
    assert result["fragility_label"] == "High"
    assert result["fragility_score"] == 60
    assert any("provider offer" in condition.lower() for condition in result["invalidating_conditions"])


def test_close_projection_and_conflicting_market_are_explained():
    prop = _strong_prop()
    prop["projection"] = 20.8
    prop["decision_receipt"]["market_probability"] = 45
    result = counterargument(prop)
    assert result["fragility_score"] == 27
    assert result["fragility_label"] == "Moderate"
    assert any("market disagrees" in reason.lower() for reason in result["risk_factors"])
