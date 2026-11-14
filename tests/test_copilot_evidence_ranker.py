from web.application.copilot_evidence_ranker import rank_player_evidence
from web.application.copilot_service import _evidence_bundle

CONTEXT = {
    "player": "Example Player", "sport": "WNBA", "stat": "Points", "platform": "PrizePicks",
    "recommendation": {"game": "DAL vs MIN", "line": 20.5},
    "query_context": {"requested_line": 19.5},
}


def _row(identifier, kind, *, line=None, game="DAL vs MIN", fresh=True):
    return {
        "id": identifier, "player": "Example Player", "sport": "WNBA", "stat": "Points",
        "platform": "PrizePicks", "game": game, "type": kind, "source": "Provider",
        "source_kind": "api", "fresh": fresh, "payload": {"line": line} if line is not None else {},
    }


def test_exact_requested_line_and_distinct_evidence_survive_history_crowding():
    rows = [_row(f"final-{index}", "final_stat", game=f"Older game {index}") for index in range(25)]
    rows.extend([
        _row("other-line", "provider_market", line=20.5),
        _row("requested-line", "provider_market", line=19.5),
        _row("forecast", "probability_forecast"),
        _row("expired", "provider_market", line=19.5, fresh=False),
    ])
    selected = rank_player_evidence(rows, CONTEXT, "Why this line?", limit=8)
    ids = [row["id"] for row in selected]
    assert ids[0] == "requested-line"
    assert "forecast" in ids
    assert any(row["type"] == "final_stat" for row in selected)
    assert "expired" not in ids
    assert len(selected) <= 8
    assert "requested posted line" in selected[0]["selection_reason"]


def test_question_matching_facts_and_bundle_cap():
    rows = [_row(f"final-{index}", "final_stat", game=f"Old {index}") for index in range(20)]
    rows.extend([_row("injury", "availability"), _row("forecast", "probability_forecast")])
    selected = rank_player_evidence(rows, CONTEXT, "Any injury update?")
    assert selected[0]["id"] == "injury"
    bundle = _evidence_bundle("player_research", {**CONTEXT, "evidence": rows}, question="Any injury update?")
    assert len(bundle["summary"]["evidence"]) <= 9
    assert len(bundle["citations"]) <= 10  # Nine ranked facts plus current market.
    assert bundle["citations"][0]["selection_reason"]


def test_expired_live_context_is_not_used_when_no_fresh_replacement():
    rows = [_row("old-line", "provider_market", line=19.5, fresh=False), _row("old-final", "final_stat", fresh=False)]
    selected = rank_player_evidence(rows, CONTEXT, "Research this player")
    assert [row["id"] for row in selected] == ["old-final"]


def test_environment_can_shrink_but_not_expand_evidence_budget(monkeypatch):
    rows = [_row(f"final-{index}", "final_stat") for index in range(15)]
    monkeypatch.setenv("EDGEIQ_COPILOT_MAX_EVIDENCE", "3")
    assert len(rank_player_evidence(rows, CONTEXT, "History")) == 3
    monkeypatch.setenv("EDGEIQ_COPILOT_MAX_EVIDENCE", "500")
    assert len(rank_player_evidence(rows, CONTEXT, "History")) == 9


def test_opponent_question_prioritizes_verified_matchup_summary_and_distinct_games():
    rows = [_row(f"log-{index}", "final_stat", game="DAL vs MIN") for index in range(12)]
    for row in rows:
        row["payload"] = {"game_date": "2026-07-01", "actual": 20}
    rows.extend([
        _row("matchup", "nba_points_history"),
        _row("forecast", "probability_forecast"),
        _row("other-game", "final_stat", game="DAL vs NY"),
    ])
    selected = rank_player_evidence(rows, CONTEXT, "How did she score against this opponent?", limit=5)
    assert selected[0]["id"] == "matchup"
    assert "opponent-specific history" in selected[0]["selection_reason"]
    assert "forecast" in {row["id"] for row in selected}
    assert len([row for row in selected if row["type"] == "final_stat" and row["game"] == "DAL vs MIN"]) == 1
    assert "other-game" in {row["id"] for row in selected}


def test_repeated_matchup_on_different_dates_keeps_both_games():
    rows = [_row("first", "final_stat"), _row("second", "final_stat")]
    rows[0]["payload"] = {"game_date": "2026-07-01", "actual": 20}
    rows[1]["payload"] = {"game_date": "2026-07-09", "actual": 24}
    assert {row["id"] for row in rank_player_evidence(rows, CONTEXT, "History")} == {"first", "second"}
