from datetime import UTC, datetime, timedelta

from web.application.copilot_outcome_eval import eligible_cases, evaluate_cases, pregame_bundle


def _case(identifier=1, **overrides):
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=identifier)
    row = {
        "id": identifier, "player_identity_id": 10, "independent_market_key": f"market-{identifier}",
        "model_version": "v2", "legacy_quarantined": False, "outcome_source": "nba_api",
        "feature_as_of": start - timedelta(hours=2), "predicted_at": start - timedelta(hours=1),
        "game_time": start, "settled_at": start + timedelta(hours=3), "outcome": "Win",
        "actual": 25, "line": 19.5, "projection": 22, "probability": 60,
        "player": "Test Player", "team": "ABC", "sport": "NBA", "stat": "Points",
        "platform": "PrizePicks", "game": "ABC vs XYZ", "direction": "Over",
    }
    return row | overrides


def test_only_locked_verified_independent_pregame_cases_enter_holdout():
    rows = [_case(1), _case(2, independent_market_key="market-1"), _case(3, feature_as_of="2026-01-04T01:00:00Z"),
            _case(4, outcome_source="manual"), _case(5, legacy_quarantined=True), _case(6)]
    assert [row["id"] for row in eligible_cases(rows)] == [1, 6]


def test_prompt_does_not_contain_settled_result_or_actual():
    bundle = pregame_bundle(_case())
    assert "Win" not in str(bundle)
    assert "actual" not in str(bundle)
    assert "settled_at" not in str(bundle)
    assert {row["id"] for row in bundle["citations"]} == {"pregame-forecast", "pregame-offer"}


def test_report_separates_llm_grounding_from_forecast_brier():
    def analyst(_question, bundle, *, model):
        assert model == "local-test"
        assert "outcome" not in str(bundle)
        return {"answer": "The line is 19.5; injury status is unknown.", "citations": ["pregame-offer"]}, None

    report = evaluate_cases([_case(1), _case(2, outcome="Loss")], model="local-test", analyst=analyst)
    assert report["cases"] == 2
    assert report["grounding_rate"] == 1
    assert report["forecast_brier"] == 0.26
    assert report["by_sport"]["NBA"]["cases"] == 2
    assert report["qualified"] is False


def test_recent_cases_are_balanced_across_sports():
    rows = [_case(index) for index in range(1, 8)]
    rows += [_case(8, sport="MLB"), _case(9, sport="NHL")]
    selected = eligible_cases(rows, limit=6)
    assert {row["sport"] for row in selected} == {"NBA", "MLB", "NHL"}
    assert [row["predicted_at"] for row in selected] == sorted(row["predicted_at"] for row in selected)
