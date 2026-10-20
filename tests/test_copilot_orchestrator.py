import pytest

from web.application.copilot_commands import QueryPlan, plan_command
from web.application.copilot_orchestrator import _Budget, run_workflow
from web.application.copilot_service import copilot_query_payload
from web.application.copilot_tools import ToolContext
from web.schemas import CopilotQueryPayload


def _context(*, stale=False, record=None, portfolio=None):
    return ToolContext(
        cached_briefing=lambda _platform, _sport: {
            "top_opportunities": [
                {"player": "Already Exposed", "sport": "WNBA", "stat": "Points", "confidence": 70},
                {"player": "New Player", "sport": "WNBA", "stat": "Assists", "confidence": 63},
            ],
            "cache": {"stale": stale},
        },
        portfolio=lambda: portfolio if portfolio is not None else {
            "pending_real_entries": 1,
            "top_players": [{"key": "already exposed", "label": "Already Exposed"}],
        },
        track_record=record if record is not None else lambda **_kwargs: {"settled_predictions": 27},
    )


def test_slate_validation_uses_two_read_only_sources():
    question = "How trustworthy are today's WNBA recommendations?"
    plan = plan_command(CopilotQueryPayload(question=question))
    assert plan and plan.intent == "model_track_record"
    result = run_workflow(plan, question, "PrizePicks", _context())
    assert result["execution"]["tool_calls"] == 2
    assert result["execution"]["model_calls"] == 0
    assert set(result["response"]["citations"]) == {"briefing-snapshot", "model-track-record"}
    assert "27 predictions" in result["response"]["answer"]
    assert "not necessarily the same players" in result["response"]["missing_information"][0]


def test_expired_slate_does_not_query_track_record():
    result = run_workflow(
        QueryPlan(intent="model_track_record", sport="WNBA"),
        "How trustworthy are today's WNBA recommendations?", "PrizePicks",
        _context(stale=True, record=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected read"))),
    )
    assert result["execution"]["tool_calls"] == 1
    assert "expired" in result["response"]["answer"]


def test_partial_failure_does_not_invent_validation():
    result = run_workflow(
        QueryPlan(intent="model_track_record", sport="WNBA"),
        "How trustworthy are today's WNBA recommendations?", "PrizePicks",
        _context(record=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider detail"))),
    )
    assert result["response"]["citations"] == ["briefing-snapshot"]
    assert "no validation claim" in result["response"]["missing_information"][0]


def test_portfolio_shortlist_is_labeled_as_incomplete_research():
    question = "Show WNBA props without increasing concentration"
    plan = plan_command(CopilotQueryPayload(question=question))
    assert plan and plan.intent == "portfolio_risk"
    result = run_workflow(plan, question, "PrizePicks", _context())
    assert result["execution"]["tool_calls"] == 2
    assert "New Player" in " ".join(result["response"]["supporting_evidence"])
    assert "Already Exposed" not in " ".join(result["response"]["supporting_evidence"])
    assert "not cleared paid picks" in " ".join(result["response"]["missing_information"])


def test_budget_rejects_third_tool_call():
    budget = _Budget(_context())
    budget.read("portfolio_risk", {})
    budget.read("portfolio_risk", {})
    with pytest.raises(TimeoutError):
        budget.read("portfolio_risk", {})


def test_environment_can_shrink_but_not_expand_tool_budget(monkeypatch):
    monkeypatch.setenv("EDGEIQ_COPILOT_MAX_TOOL_CALLS", "1")
    budget = _Budget(_context())
    budget.read("portfolio_risk", {})
    with pytest.raises(TimeoutError):
        budget.read("portfolio_risk", {})
    monkeypatch.setenv("EDGEIQ_COPILOT_MAX_TOOL_CALLS", "20")
    budget = _Budget(_context())
    budget.read("portfolio_risk", {})
    budget.read("portfolio_risk", {})
    with pytest.raises(TimeoutError):
        budget.read("portfolio_risk", {})


def test_copilot_service_uses_bounded_portfolio_workflow():
    context = _context()
    result = copilot_query_payload(
        CopilotQueryPayload(question="Show WNBA props without increasing concentration", sport="WNBA"),
        player_research=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected research")),
        loss_review=lambda: {}, briefing=context.cached_briefing, portfolio=context.portfolio,
    )
    assert result["intent"] == "portfolio_shortlist"
    assert result["execution"] == {
        "workflow": "portfolio_shortlist", "tool_calls": 2, "model_calls": 0,
        "planner": "rules", "ollama_usage": {},
    }
