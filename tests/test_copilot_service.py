from web.application import copilot_service
from web.schemas import CopilotQueryPayload, RecommendationExplainPayload


def _answer(citations, answer="The verified line is 19.5."):
    return {
        "answer": answer,
        "recommendation": "Keep this in paper mode.",
        "supporting_evidence": ["Verified final"],
        "counterargument": "History is limited.",
        "missing_information": ["Injury status"],
        "suggested_correction": "Wait for stronger evidence.",
        "citations": citations,
    }


def test_player_research_routes_to_verified_history(monkeypatch):
    calls = []
    monkeypatch.setattr(copilot_service, "ollama_structured", lambda *_args, **_kwargs: (_answer(["final-1"]), None))

    result = copilot_service.copilot_query_payload(
        CopilotQueryPayload(question="Research this player", player="Paige Bueckers", stat="Points", line=19.5),
        player_research=lambda *args: calls.append(args) or {"chart": [{"game": "DAL vs MIN", "result": 22}], "recommendation": {"line": 19.5}},
        loss_review=lambda: {}, briefing=lambda *_args: {}, portfolio=lambda: {},
    )

    assert result["intent"] == "player_research"
    assert result["provider"] == "Ollama"
    assert result["response"]["citations"] == ["final-1"]
    assert calls[0][0:2] == ("Paige Bueckers", "Points")


def test_copilot_rejects_invented_citation(monkeypatch):
    monkeypatch.setattr(copilot_service, "ollama_structured", lambda *_args, **_kwargs: (_answer(["internet-1"]), None))

    result = copilot_service.copilot_query_payload(
        CopilotQueryPayload(question="Review portfolio exposure"),
        player_research=lambda *_args: {}, loss_review=lambda: {}, briefing=lambda *_args: {},
        portfolio=lambda: {"pending_entries": 3},
    )

    assert result["provider"] == "EdgeIQ Local"
    assert result["ai_error"]
    assert set(result["response"]["citations"]) == {"portfolio-snapshot"}


def test_copilot_falls_back_cleanly_when_ollama_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        copilot_service,
        "ollama_structured",
        lambda *_args, **_kwargs: (None, "Ollama is not running."),
    )

    result = copilot_service.copilot_query_payload(
        CopilotQueryPayload(question="Review portfolio exposure"),
        player_research=lambda *_args: {}, loss_review=lambda: {}, briefing=lambda *_args: {},
        portfolio=lambda: {"pending_entries": 3},
    )

    assert result["provider"] == "EdgeIQ Local"
    assert result["grounded"] is True
    assert result["response"]["answer"]
    assert "not running" in result["ai_error"]


def test_recommendation_explanation_rejects_invented_number(monkeypatch):
    monkeypatch.setattr(
        copilot_service, "ollama_structured",
        lambda *_args, **_kwargs: (_answer(["selected-card"], "This has a 99% chance."), None),
    )
    result = copilot_service.explain_recommendation_payload(
        RecommendationExplainPayload(suggestion={"grade": "B", "entry": {"props": []}}),
    )

    assert result["provider"] == "EdgeIQ Local"
    assert "number" in result["ai_error"]


def test_grounding_accepts_equivalent_number_formatting() -> None:
    answer = _answer(["selected-card"], "The verified line is 19.50.")
    bundle = {
        "citations": [{"id": "selected-card", "data": {"line": 19.5}}],
        "summary": {"line": 19.5},
    }

    assert copilot_service._unsupported_numbers(answer, bundle) is False


def test_grounding_ignores_digits_inside_citation_ids() -> None:
    answer = _answer(["ev-806a5f1a99754930"], "Use the verified evidence.")
    bundle = {
        "citations": [{"id": "ev-806a5f1a99754930", "data": {"line": 19.5}}],
        "summary": {"line": 19.5},
    }

    assert copilot_service._unsupported_numbers(answer, bundle) is False


def test_copilot_requires_forecast_citation_for_projection_claim() -> None:
    answer = _answer(["market-1"], "The projection is 19.5 with 57% confidence.")
    answer["counterargument"] = "Uncertainty remains."
    bundle = {
        "citations": [
            {"id": "market-1", "label": "PrizePicks · provider_market"},
            {"id": "forecast-1", "label": "EdgeIQ forecast · probability_forecast"},
        ],
    }

    assert copilot_service._citations_support_claim_types(answer, bundle) is False
    answer["citations"].append("forecast-1")
    assert copilot_service._citations_support_claim_types(answer, bundle) is True


def test_player_research_includes_requested_line_context(monkeypatch):
    captured = {}

    def fake_answer(_question, bundle, **_kwargs):
        captured["bundle"] = bundle
        return _answer(["current-market"]), None

    monkeypatch.setattr(copilot_service, "_grounded_answer", fake_answer)
    copilot_service.copilot_query_payload(
        CopilotQueryPayload(question="Research", player="A", stat="Points", line=19.5),
        player_research=lambda *_args: {"recommendation": {"line": 14.5}},
        loss_review=lambda: {}, briefing=lambda *_args: {}, portfolio=lambda: {},
    )

    assert captured["bundle"]["summary"]["query_context"]["requested_line"] == 19.5


def test_grounded_answer_retries_wrong_evidence_category(monkeypatch):
    first = _answer(["market-1"], "The projection is 19.5 with 57% confidence.")
    first["counterargument"] = "Uncertainty remains."
    revised = {**first, "citations": ["market-1", "forecast-1"]}
    responses = iter([(first, None), (revised, None)])
    monkeypatch.setattr(copilot_service, "ollama_structured", lambda *_args, **_kwargs: next(responses))
    bundle = {
        "intent": "player_research",
        "summary": {"line": 19.5, "confidence": 57},
        "citations": [
            {"id": "market-1", "label": "PrizePicks · provider_market", "data": {"line": 19.5}},
            {"id": "forecast-1", "label": "EdgeIQ forecast · probability_forecast", "data": {"confidence": 57}},
        ],
    }

    answer, error = copilot_service._grounded_answer("Research 19.5", bundle)

    assert error is None
    assert answer["citations"] == ["market-1", "forecast-1"]


def test_requested_line_cannot_be_replaced_by_another_evidence_line() -> None:
    bundle = {
        "summary": {"query_context": {"requested_line": 19.5}},
        "citations": [],
    }

    assert copilot_service._misstates_requested_line(
        {"answer": "The requested line is 14.5 points."}, bundle,
    ) is True
    assert copilot_service._misstates_requested_line(
        {"answer": "The requested line is 19.5; the current offer is 14.5."}, bundle,
    ) is False


def test_copilot_rejects_misread_opponent_evidence(monkeypatch):
    monkeypatch.setattr(
        copilot_service, "ollama_structured",
        lambda *_args, **_kwargs: (
            _answer(["briefing-snapshot"], "The opponent's mean is based on the player's game log."), None,
        ),
    )
    result = copilot_service.copilot_query_payload(
        CopilotQueryPayload(question="Narrate today's briefing"),
        player_research=lambda *_args: {}, loss_review=lambda: {},
        briefing=lambda *_args: {"headline": "No cleared card"}, portfolio=lambda: {},
    )

    assert result["provider"] == "EdgeIQ Local"
    assert "matchup" in result["ai_error"]
