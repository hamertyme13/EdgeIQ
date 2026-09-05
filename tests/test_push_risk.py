from analytics.push_risk import push_risk


def test_half_point_line_with_verified_role_has_low_push_risk() -> None:
    result = push_risk({
        "line": 20.5,
        "stat": "Points",
        "provider_player_id": "player-1",
        "forecast_snapshot": {
            "standard_deviation": 4.0,
            "features": {"role_evidence_verified": True},
            "distribution": {"expected_result": 22.0},
        },
    })

    assert result["level"] == "Low"
    assert result["estimated_tie_probability"] == 0


def test_integer_line_and_missing_role_evidence_raise_push_risk() -> None:
    result = push_risk({
        "line": 20,
        "stat": "Points",
        "forecast_snapshot": {
            "standard_deviation": 3.0,
            "features": {"role_evidence_verified": False},
            "distribution": {"expected_result": 20.0},
        },
    })

    assert result["whole_number_line"] is True
    assert result["estimated_tie_probability"] > 10
    assert result["availability_risk"] == 18
    assert result["level"] == "High"
