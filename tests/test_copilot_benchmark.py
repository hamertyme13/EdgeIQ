from web.application.copilot_benchmark import ANALYST_CASES, PLANNER_CASES, run_preview
from web.application.copilot_commands import QueryPlan


def test_planner_preview_records_failures_without_qualification():
    def planner(payload, *, model, diagnostic):
        assert model == "test-model"
        assert diagnostic is True
        if "delete" in payload.question:
            return None, {"model_response_received": True}
        return QueryPlan(intent="market_filter"), {"model_response_received": True}

    result = run_preview("planner", "test-model", planner=planner)
    assert result["cases_run"] == 20
    assert result["combined_suite_cases"] == 40
    assert result["security_passed"] is False
    assert result["passed"] < result["cases_run"]
    assert result["qualified"] is False


def test_analyst_preview_requires_grounded_citation_and_missing_information():
    def analyst(question, bundle, *, model):
        assert model == "test-model"
        assert bundle["citations"][0]["id"] == "selected-card"
        return {"citations": ["selected-card"], "missing_information": []}, None

    result = run_preview("analyst", "test-model", analyst=analyst)
    assert result["cases_run"] == 20
    assert not next(row for row in result["cases"] if row["id"] == "injury")["passed"]
    assert result["qualified"] is False


def test_preview_rejects_unknown_role():
    try:
        run_preview("vision", "test-model")
    except ValueError as exc:
        assert "role" in str(exc)
    else:
        assert False


def test_case_ids_are_stable_and_unique():
    assert len(PLANNER_CASES) == len(ANALYST_CASES) == 20
    assert len({case.id for case in PLANNER_CASES}) == 20
    assert len({case.id for case in ANALYST_CASES}) == 20


def test_model_outage_cannot_pass_security_gate():
    result = run_preview(
        "planner", "offline", repetitions=3,
        planner=lambda *_args, **_kwargs: (None, {"model_response_received": False}),
    )
    assert result["attempts"] == 60
    assert result["security_passed"] is False
    assert result["automatic_gates_passed"] is False
    assert result["qualified"] is False


def test_analyst_injection_echo_fails_security_case():
    result = run_preview(
        "analyst", "echo",
        analyst=lambda question, _bundle, **_kwargs: (
            {"answer": question, "citations": ["selected-card"], "missing_information": ["Unknown"]}, None,
        ),
    )
    assert result["security_passed"] is False
    assert result["forbidden_claims"] >= 1
    assert result["qualified"] is False


def test_safe_runtime_fallback_is_reported_but_not_qualified():
    result = run_preview(
        "analyst", "fallback", repetitions=3,
        analyst=lambda *_args, **_kwargs: (None, "Grounding rejected the draft."),
    )
    assert result["runtime_fallbacks"] == 60
    assert result["forbidden_claims"] == 0
    assert result["security_passed"] is False
    assert result["automatic_gates_passed"] is False


def test_analyst_exception_keeps_security_case_in_gate():
    def broken(*_args, **_kwargs):
        raise RuntimeError("model failed")

    result = run_preview("analyst", "broken", repetitions=3, analyst=broken)
    security = [row for row in result["cases"] if row["category"] == "security"]
    assert len(security) == 12
    assert all(row["outcome"] == "model_failure" for row in security)
    assert result["security_passed"] is False
