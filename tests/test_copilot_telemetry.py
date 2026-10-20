from __future__ import annotations

import json
import logging

import pytest

from web.application import copilot_service
from web.application.copilot_telemetry import CopilotTrace
from web.schemas import CopilotQueryPayload


def _trace(caplog):
    line = next(record.message for record in caplog.records if record.message.startswith("copilot_trace "))
    return json.loads(line.removeprefix("copilot_trace "))


def test_copilot_logs_stage_timings_without_question_or_player(caplog):
    question = "Which recommendations are based on stale evidence? PRIVATE_QUERY_MARKER"
    with caplog.at_level(logging.INFO, logger="web.application.copilot_telemetry"):
        result = copilot_service.copilot_query_payload(
            CopilotQueryPayload(question=question),
            player_research=lambda *_args: {}, loss_review=lambda: {},
            briefing=lambda *_args: {"top_opportunities": []}, portfolio=lambda: {},
        )
    trace = _trace(caplog)
    assert result["intent"] == "evidence_review"
    assert trace["intent"] == "evidence_review"
    assert trace["failed"] is False
    assert trace["total_ms"] >= trace["planning_ms"] + trace["retrieval_ms"]
    assert "PRIVATE_QUERY_MARKER" not in caplog.text
    assert "question" not in trace


def test_copilot_logs_failure_type_without_exception_message(caplog):
    def fail(*_args):
        raise RuntimeError("PRIVATE_EXCEPTION_MARKER")

    with caplog.at_level(logging.INFO, logger="web.application.copilot_telemetry"), pytest.raises(RuntimeError):
        copilot_service.copilot_query_payload(
            CopilotQueryPayload(question="Research player", player="Test Player", stat="Points"),
            player_research=fail, loss_review=lambda: {}, briefing=lambda *_args: {}, portfolio=lambda: {},
        )
    trace = _trace(caplog)
    assert trace["failed"] is True
    assert trace["failure_type"] == "RuntimeError"
    assert "PRIVATE_EXCEPTION_MARKER" not in caplog.text


def test_trace_logging_failure_does_not_interrupt_answer(monkeypatch):
    monkeypatch.setattr(CopilotTrace, "_finish", lambda *_args: (_ for _ in ()).throw(ValueError("bad trace")))
    result = copilot_service.copilot_query_payload(
        CopilotQueryPayload(question="Which recommendations are based on stale evidence?"),
        player_research=lambda *_args: {}, loss_review=lambda: {},
        briefing=lambda *_args: {"top_opportunities": []}, portfolio=lambda: {},
    )
    assert result["intent"] == "evidence_review"


def test_analyst_usage_is_aggregated_without_raw_answer(caplog, monkeypatch):
    def fake_answer(_question, _bundle, **kwargs):
        callback = kwargs["usage_callback"]
        callback({"load_duration": 100, "eval_count": 5})
        callback({"load_duration": 0, "eval_count": 3})
        return {"answer": "Grounded answer", "citations": ["final-1"]}, None

    monkeypatch.setattr(copilot_service, "_grounded_answer", fake_answer)
    with caplog.at_level(logging.INFO, logger="web.application.copilot_telemetry"):
        result = copilot_service.copilot_query_payload(
            CopilotQueryPayload(question="Research test player", player="Test Player", stat="Points"),
            player_research=lambda *_args: {"chart": [{"game": "Test game", "result": 22}]},
            loss_review=lambda: {}, briefing=lambda *_args: {}, portfolio=lambda: {},
        )
    trace = _trace(caplog)
    assert result["provider"] == "Ollama"
    assert trace["analyst_model_calls"] == 2
    assert trace["ollama"]["analyst"] == {"load_duration": 100, "eval_count": 8}
    assert "Grounded answer" not in caplog.text
