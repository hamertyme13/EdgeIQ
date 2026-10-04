from copy import deepcopy

from web.application.market_disagreement import market_disagreement_payload
from web.routers.briefing import BriefingDependencies, market_disagreement


def _prop():
    return {
        "player": "Example Player", "sport": "WNBA", "stat": "Points", "direction": "Over",
        "line": 19.5, "platform": "PrizePicks",
        "calibration_presentation": {
            "model_probability": 61, "calibrated_probability": 58,
            "segment_sample_size": 120, "uncertainty_points": 4,
        },
        "decision_receipt": {"market_consensus": {
            "available": True, "source": "The Odds API", "source_type": "multi_book_no_vig",
            "player": "Example Player", "stat": "Points", "direction": "Over", "line": 19.5,
            "market_probability": 54.55, "book_count": 2, "timestamped_book_count": 2,
            "stale": False, "age_seconds": 80,
            "books": [
                {"over_odds": -150, "under_odds": 100},
                {"over_odds": -150, "under_odds": 100},
            ],
        }},
    }


def test_exact_paired_market_shows_raw_and_calibrated_difference():
    result = market_disagreement_payload({"top_opportunities": [_prop()], "cache": {"stale": False}})
    row = result["rows"][0]
    assert row["market_probability"] == 54.55
    assert row["raw_difference"] == 6.5
    assert row["effective_difference"] == 3.5
    assert row["calibration_uncertainty_points"] == 4
    assert row["within_calibration_uncertainty"] is True
    assert row["market_book_count"] == 2


def test_mismatched_or_invalid_market_is_excluded():
    for field, value, reason in (
        ("line", 20.5, "line_mismatch"),
        ("direction", "Under", "direction_mismatch"),
        ("source_type", "single_book", "no_paired_market"),
        ("stale", True, "stale_market"),
        ("market_probability", 90, "probability_conflict"),
    ):
        prop = deepcopy(_prop())
        prop["decision_receipt"]["market_consensus"][field] = value
        result = market_disagreement_payload({"top_opportunities": [prop]})
        assert not result["rows"]
        assert result["excluded"][reason] == 1
    prop = deepcopy(_prop())
    prop["decision_receipt"]["market_consensus"]["books"][0]["under_odds"] = 0
    assert market_disagreement_payload({"top_opportunities": [prop]})["excluded"]["invalid_odds"] == 1


def test_stale_briefing_never_presents_current_disagreement():
    result = market_disagreement_payload({"top_opportunities": [_prop()], "cache": {"stale": True}})
    assert result["rows"] == []
    assert result["excluded"] == {"stale_briefing": 1}


def test_endpoint_reads_cached_briefing_without_refresh():
    calls = []
    deps = BriefingDependencies(
        briefing=lambda platform, sport, refresh, cached_only: calls.append((platform, sport, refresh, cached_only)) or {"top_opportunities": [_prop()]},
        new_scan=lambda *_args: {}, save_scan=lambda scan: scan,
        run_scan=lambda *_args: {}, scan_status=lambda *_args: {},
    )
    result = market_disagreement(platform="PrizePicks", sport="WNBA", deps=deps)
    assert result["rows"][0]["raw_difference"] == 6.5
    assert calls == [("PrizePicks", "WNBA", False, True)]
