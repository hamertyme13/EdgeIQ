from web.application.discounted_offer_comparison import attach_discounted_options


def _standard() -> dict:
    return {
        "player": "Test Player", "sport": "WNBA", "stat": "Points", "platform": "PrizePicks",
        "game": "AAA @ BBB", "game_time": "2026-11-03T00:00:00+00:00",
        "line": 20.5, "direction": "Over", "line_offer_type": "standard", "score": 74,
        "confidence": 61,
        "forecast_snapshot": {
            "projection": 21.0, "probability": 54.0, "standard_deviation": 5.0,
            "sample_size": 20, "effective_sample_size": 15.0,
            "source": "verified_history_distribution", "model_version": "test", "paid_eligible": False,
            "reason": "", "feature_as_of": "2026-11-02T00:00:00+00:00",
            "features": {"evidence_strength": 1.0}, "distribution": {},
        },
    }


def _discount(line: float, **changes) -> dict:
    return {
        "player": "Test Player", "league": "WNBA", "stat": "Points", "platform": "PrizePicks",
        "game": "AAA @ BBB", "game_time": "2026-11-03T00:00:00+00:00",
        "line": line, "line_offer_type": "goblin", "allowed_directions": ["Over"], **changes,
    }


def test_discounted_comparison_uses_closest_favorable_offer_without_changing_standard() -> None:
    standard = _standard()
    attach_discounted_options([standard], [
        _discount(16.5), _discount(18.5), _discount(24.5),
        _discount(19.5, game="CCC @ DDD"),
    ], [])

    assert standard["line"] == 20.5
    assert standard["score"] == 74
    assert standard["confidence"] == 61
    assert standard["discounted_option"]["line"] == 18.5
    assert standard["discounted_option"]["offer_type"] == "goblin"
    assert 0 < standard["discounted_option"]["probability"] <= 65


def test_discounted_comparison_never_borrows_another_game_or_unsupported_side() -> None:
    standard = _standard()
    attach_discounted_options([standard], [
        _discount(18.5, game="CCC @ DDD"),
        _discount(17.5, allowed_directions=["Under"]),
    ], [])
    assert "discounted_option" not in standard


def test_discounted_comparison_discloses_unavailable_probability() -> None:
    standard = _standard()
    standard["forecast_snapshot"] = {}
    attach_discounted_options([standard], [_discount(18.5)], [])
    assert standard["discounted_option"]["probability"] is None
