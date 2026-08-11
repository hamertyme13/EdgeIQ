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
