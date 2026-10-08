from web.application.copilot_commands import plan_command, run_command
from web.schemas import CopilotQueryPayload


def _services(**overrides):
    services = {
        "platform": "PrizePicks",
        "briefing": lambda _platform, _sport: {"top_opportunities": []},
        "portfolio": lambda: {},
        "personal_edge": lambda _mode: {},
        "timeline": lambda **_kwargs: {"events": []},
    }
    services.update(overrides)
    return services


def test_market_filter_requires_matching_segment_samples():
    question = "Show me WNBA props above 60% model probability with at least 100 calibrated samples"
    plan = plan_command(CopilotQueryPayload(question=question))
    assert plan and plan.intent == "market_filter"
    assert plan.sport == "WNBA"
    assert plan.min_samples == 100
    rows = [
        {"player": "A", "sport": "WNBA", "stat": "Points", "line": 20.5, "confidence": 75,
         "calibration_presentation": {"status": "CALIBRATED", "sample_size": 400, "segment_sample_size": 10}},
        {"player": "B", "sport": "WNBA", "stat": "Rebounds", "line": 8.5, "confidence": 64,
         "calibration_presentation": {"status": "CALIBRATED", "sample_size": 300, "segment_sample_size": 120}},
        {"player": "C", "sport": "WNBA", "stat": "Assists", "line": 5.5, "confidence": 80,
         "calibration_presentation": {"status": "UNAVAILABLE", "sample_size": 300, "segment_sample_size": 120}},
    ]
    result = run_command(plan, **_services(briefing=lambda *_args: {"top_opportunities": rows}))
    assert "B" in result["response"]["answer"]
    assert "Points" not in result["response"]["answer"]
    assert "Assists" not in result["response"]["answer"]
    assert result["response"]["citations"] == ["briefing-snapshot"]
    assert result["provider"] == "EdgeIQ Local"


def test_portfolio_command_uses_existing_risk_response():
    plan = plan_command(CopilotQueryPayload(question="Which open entries have the most correlated risk?"))
    assert plan and plan.intent == "portfolio_risk"
    result = run_command(plan, **_services(portfolio=lambda: {
        "concentration_risk": "HIGH", "pending_real_entries": 3, "open_wager": 40,
        "shared_leg_failure_risk": {"repeated_props": 2},
        "risk_reasons": ["A shared market limit is exceeded."],
        "top_risk_entries": [{"id": 42, "platform": "PrizePicks", "repeated_markets": 2, "shared_games": 1}],
    }))
    assert "HIGH concentration risk" in result["response"]["answer"]
    assert any("Entry #42" in row for row in result["response"]["supporting_evidence"])
    assert "portfolio-snapshot" in result["response"]["citations"]


def test_timeline_needs_player_instead_of_querying_every_market():
    plan = plan_command(CopilotQueryPayload(question="Why did this pick fall from A to C?"))
    assert plan and plan.intent == "timeline"
    result = run_command(plan, **_services(timeline=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not query"))))
    assert result["grounded"] is False
    assert "Choose a player" in result["response"]["answer"]
    assert result["citations"] == []


def test_slate_change_command_reads_cached_comparison_without_timeline():
    plan = plan_command(CopilotQueryPayload(question="What changed since noon?"))
    assert plan and plan.intent == "slate_changes"
    result = run_command(plan, **_services(
        briefing=lambda *_args: {"slate_changes": {
            "available": True, "event_count": 2,
            "counts": {"new_recommendations": 1, "upgrades": 1},
            "events": [{"label": "A · Points", "detail": "Line: 18.5 to 19.5"}],
        }},
        timeline=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not query timeline")),
    ))
    assert "2 observed changes" in result["response"]["answer"]
    assert "Line: 18.5 to 19.5" in result["response"]["supporting_evidence"][-1]
    assert result["response"]["citations"] == ["briefing-slate-comparison"]


def test_timeline_command_reports_observed_change_without_inventing_cause():
    plan = plan_command(CopilotQueryPayload(question="Why did this pick fall from A to C?", player="A"))
    result = run_command(plan, **_services(timeline=lambda **_kwargs: {
        "events": [{"player": "A", "stat": "Points", "changes": ["recommendation_grade_change"],
                    "change_reasons": ["Grade: A to C.", "The saved snapshots do not identify the cause."]}],
        "summary": "Two saved states.",
    }))
    text = " ".join([result["response"]["answer"], *result["response"]["supporting_evidence"]])
    assert "because" not in text
    assert "Grade: A to C." in text


def test_personal_edge_uses_verified_ledger_summary():
    plan = plan_command(CopilotQueryPayload(question="Show me my strongest historical segments"))
    assert plan and plan.intent == "personal_edge"
    result = run_command(plan, **_services(personal_edge=lambda mode: {
        "summary": {"verified_leg_decisions": 35, "settled_entries": 18},
        "strongest": {"name": "WNBA", "wins": 22, "losses": 13, "decisions": 35},
    }))
    assert "35 verified leg decisions" in result["response"]["answer"]
    assert "WNBA" in result["response"]["supporting_evidence"][0]


def test_stale_evidence_command_filters_cached_rows():
    plan = plan_command(CopilotQueryPayload(question="Which recommendations are based on stale evidence?"))
    assert plan and plan.evidence_filter == "stale"
    rows = [
        {"player": "Fresh", "sport": "WNBA", "recommendation_freshness": {"status": "fresh"}},
        {"player": "Expired", "sport": "WNBA", "recommendation_freshness": {"status": "expired"}},
    ]
    result = run_command(plan, **_services(briefing=lambda *_args: {"top_opportunities": rows}))
    assert "Expired" in result["response"]["answer"]
    assert "Fresh" not in result["response"]["answer"]


def test_model_track_record_requires_sport_and_reuses_ledger():
    no_sport = plan_command(CopilotQueryPayload(question="Show model track record"))
    assert no_sport and no_sport.intent == "model_track_record"
    result = run_command(no_sport, **_services(track_record=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not query"))))
    assert result["grounded"] is False
    selected = plan_command(CopilotQueryPayload(question="Show WNBA model track record"))
    assert selected and selected.sport == "WNBA"
    result = run_command(selected, **_services(track_record=lambda **_kwargs: {
        "settled_predictions": 42,
        "versions": [{"model_version": "v2.4", "platform": "PrizePicks", "settled_predictions": 42, "actual_hit_rate": 54.8}],
    }))
    assert "42 verified settled predictions" in result["response"]["answer"]
    assert "v2.4" in result["response"]["supporting_evidence"][0]
    assert result["response"]["citations"] == ["model-track-record"]


def test_market_disagreement_command_uses_validated_cached_evidence():
    plan = plan_command(CopilotQueryPayload(question="Find the biggest disagreements between EdgeIQ and the market"))
    assert plan and plan.intent == "market_disagreement"
    result = run_command(plan, **_services(briefing=lambda *_args: {"top_opportunities": []}))
    assert "No current top opportunity" in result["response"]["answer"]
    assert result["response"]["citations"] == ["briefing-market-snapshot"]


def test_unrecognized_question_keeps_existing_copilot_path():
    assert plan_command(CopilotQueryPayload(question="Research this player's recent minutes")) is None
