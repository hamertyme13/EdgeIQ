from datetime import UTC, datetime, timedelta

import pytest

from analytics.game_features import prop_opportunity_context
from analytics.game_model_evaluation import promotion_evidence
from analytics.game_model_registry import (
    GAME_CONTEXT_CHALLENGER_VERSION as CHALLENGER,
)
from analytics.game_model_registry import (
    GAME_HISTORICAL_BASELINE_VERSION as HISTORY,
)
from analytics.game_model_registry import (
    GAME_MARKET_CHAMPION_VERSION as MARKET,
)
from analytics.game_model_registry import (
    promotion_decision,
)
from analytics.game_prediction import predict_game
from data.providers.espn import basketball_box_score_pace
from repository.repositories.game_prediction_repository import GamePredictionRepository
from repository.repositories.team_history_repository import TeamHistoryRepository
from services import game_intelligence
from services.game_team_features import team_history_features
from web.application.game_intelligence_service import evaluation_payload


def _cohort(count=800):
    rows = []
    for index in range(count):
        start = datetime(2020, 1, 1, 19, tzinfo=UTC) + timedelta(days=index)
        shared = {
            "sport": "WNBA", "game_id": f"gate-{index}", "game_start": start.isoformat(),
            "generated_at": (start - timedelta(hours=4)).isoformat(),
            "settled_at": (start + timedelta(hours=3)).isoformat(), "outcome_source": "espn_official_scoreboard",
            "actual_home_win": 1.0, "evidence": {"historical_sample_size": 30},
        }
        for version, probability in ((CHALLENGER, 0.96), (MARKET, 0.65), (HISTORY, 0.75)):
            rows.append(shared | {"model_version": version, "home_win_probability": probability})
    return rows


def test_promotion_uses_independent_shared_holdout_and_both_baselines(monkeypatch):
    rows = _cohort()
    monkeypatch.setattr(GamePredictionRepository, "latest", lambda **kwargs: rows + rows)
    payload = evaluation_payload()
    assert payload["promotion_evidence"]["independent_games"] == 800
    assert payload["promotion_evidence"]["holdout_games"] == 200
    assert payload["promotion"]["promotable"] is True
    for baseline in (MARKET, HISTORY):
        stronger = [row | {"home_win_probability": 0.99} if row["model_version"] == baseline else row for row in rows]
        assert promotion_decision(promotion_evidence(stronger)["metrics"])["promotable"] is False


@pytest.mark.parametrize("invalid", ["late", "missing_baseline", "missing_history", "inconsistent_outcome", "missing_source"])
def test_invalid_cohorts_never_promote(invalid):
    rows = _cohort()
    if invalid == "late":
        rows = [row | {"generated_at": row["settled_at"]} for row in rows]
    elif invalid == "missing_baseline":
        rows = [row for row in rows if row["model_version"] != HISTORY]
    elif invalid == "missing_history":
        rows = [row | {"evidence": {}} for row in rows]
    elif invalid == "inconsistent_outcome":
        rows = [row | {"actual_home_win": 0.0} if row["model_version"] == HISTORY else row for row in rows]
    else:
        rows = [row | {"outcome_source": ""} for row in rows]
    assert promotion_decision(promotion_evidence(rows)["metrics"])["promotable"] is False


def test_historical_baseline_scores_do_not_depend_on_market():
    features = {"historical_home_probability": 0.7, "historical_sample_size": 20,
                "historical_expected_home_points": 88, "historical_expected_away_points": 80}
    first = predict_game(features | {"market_total": 100, "market_home_margin": -20}, model_version=HISTORY)
    second = predict_game(features | {"market_total": 250, "market_home_margin": 20}, model_version=HISTORY)
    assert first.expected_total == second.expected_total == 168
    assert first.expected_margin == second.expected_margin == 8


def test_history_excludes_future_duplicates_and_preserves_zero_win_rate():
    prior = {"game_id": "prior", "game_start": "2026-07-01T19:00:00Z", "home_team": "A", "away_team": "B",
             "actual_home_points": 70, "actual_away_points": 90, "actual_home_win": 0.0}
    future = prior | {"game_id": "future", "game_start": "2026-09-01T19:00:00Z", "actual_home_win": 1.0}
    features = team_history_features("WNBA", "A", "B", "2026-08-01T19:00:00Z", [prior, prior, future])
    assert features["historical_sample_size"] == 1
    assert features["team_features"]["home"]["recent_win_rate"] == 0.0
    assert features["historical_home_probability"] < 0.5
    assert features["team_features"]["home"]["estimated_pace"] is None


def test_official_outcome_resolves_different_provider_id_and_settles_all_models():
    start = datetime.now(UTC) - timedelta(days=1)
    generated = (start - timedelta(hours=3)).isoformat()
    for version in (MARKET, HISTORY, CHALLENGER):
        prediction = predict_game({"game_id": "odds-provider-unique", "sport": "WNBA", "game": "A @ B",
                                   "home_team": "B", "away_team": "A", "game_start": start.isoformat()}, model_version=version).snapshot()
        GamePredictionRepository.save(prediction | {"generated_at": generated})
    outcome = {"game_id": "espn-other-id", "sport": "WNBA", "game": "A @ B", "game_start": start.isoformat(),
               "home_team": "B", "away_team": "A", "home_points": 90, "away_points": 80, "source": "espn_official_scoreboard"}
    assert GamePredictionRepository.settle_outcome(outcome | {"home_team": "A", "away_team": "B"}) == 0
    assert GamePredictionRepository.settle_outcome(outcome) == 3
    assert GamePredictionRepository.settle_outcome(outcome) == 0
    assert all(row["actual_home_win"] == 1 for row in GamePredictionRepository.latest_for_game("odds-provider-unique"))
    TeamHistoryRepository.save_outcomes([outcome])
    TeamHistoryRepository.save_outcomes([outcome])
    history = TeamHistoryRepository.before("WNBA", (datetime.now(UTC) + timedelta(days=1)).isoformat())
    assert len([row for row in history if row["game_id"] == "espn-other-id"]) == 1
    assert TeamHistoryRepository.before("WNBA", (start - timedelta(days=1)).isoformat()) == []


def test_possession_pace_requires_complete_box_scores():
    stats = [{"name": name, "displayValue": value} for name, value in (
        ("fieldGoalsMade-fieldGoalsAttempted", "30-70"), ("freeThrowsMade-freeThrowsAttempted", "15-20"),
        ("offensiveRebounds", "8"), ("turnovers", "10"),
    )]
    summary = {"boxscore": {"teams": [{"statistics": stats}, {"statistics": stats}]}}
    assert basketball_box_score_pace(summary, "WNBA") == 80.8
    assert basketball_box_score_pace({"boxscore": {"teams": [{"statistics": stats}]}}, "WNBA") is None


def test_opportunity_telemetry_only_emits_for_non_neutral_factor(caplog):
    with caplog.at_level("INFO", logger="analytics.game_features"):
        prop_opportunity_context("NFL", "Receiving Yards", "A", {"home_team": "A", "expected_margin": 0}, expected_opportunities=8)
        assert not caplog.records
        result = prop_opportunity_context("NFL", "Receiving Yards", "A", {"home_team": "A", "expected_margin": -10}, expected_opportunities=8)
    assert result["game_context_influenced_prop"] is True
    assert caplog.records[-1].event_name == "game_context_influenced_prop"


def test_slate_persists_history_backed_three_model_cohort(monkeypatch):
    now = datetime.now(UTC)
    target = (now + timedelta(days=1)).isoformat()
    outcome = {
        "sport": "WNBA", "game_id": "independent-slate-history", "game": "Wings @ Lynx",
        "home_team": "Minnesota Lynx", "away_team": "Dallas Wings",
        "game_start": (now - timedelta(days=1)).isoformat(), "home_points": 90, "away_points": 70,
        "source": "espn_official_scoreboard", "pace": 80,
    }
    TeamHistoryRepository.save_outcomes([outcome])
    game = {
        "id": "history-backed-slate", "home_team": "Minnesota Lynx", "away_team": "Dallas Wings",
        "commence_time": target, "bookmakers": [{"key": "fixture", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Minnesota Lynx", "price": -100}, {"name": "Dallas Wings", "price": -100},
        ]}]}],
    }
    monkeypatch.setattr(game_intelligence, "collect_team_history", lambda sport: {"stored": 0})
    monkeypatch.setattr(game_intelligence, "fetch_injuries", lambda sport: [])
    monkeypatch.setattr(game_intelligence.odds, "get_games", lambda sport: [game])
    row = game_intelligence.predict_slate("WNBA")[0]
    assert row["historical_baseline"]["evidence"]["historical_sample_size"] == 1
    assert row["champion"]["home_win_probability"] == 0.5
    assert row["challenger"]["home_win_probability"] > 0.5
    snapshots = GamePredictionRepository.latest_for_game("history-backed-slate")
    assert len(snapshots) == 3
    assert len({snapshot["generated_at"] for snapshot in snapshots}) == 1
