from __future__ import annotations

import requests
from pydantic import BaseModel, ConfigDict

from services.ollama_client import (
    ollama_chat,
    ollama_keep_alive,
    ollama_model,
    ollama_predict_limit,
    ollama_role_model,
    ollama_status,
    ollama_structured,
    ollama_typed,
    ollama_vision_structured,
)
from web.app import _ollama_card_identity_mismatch, _unsupported_ollama_matchup_claim


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class TypedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str


def test_ollama_typed_validates_schema_and_records_usage(monkeypatch):
    monkeypatch.setenv("OLLAMA_PLANNER_MODEL", "planner-test")
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs)
        return Response({"message": {"content": '{"intent":"market_filter"}'}, "eval_count": 9})

    value, error, usage = ollama_typed([{"role": "user", "content": "Find props"}], TypedReply, post=post)

    assert error is None
    assert value and value.intent == "market_filter"
    assert usage == {"eval_count": 9}
    assert calls[0]["json"]["model"] == "planner-test"
    assert calls[0]["json"]["format"] == TypedReply.model_json_schema()


def test_ollama_typed_rejects_extra_fields_and_fails_closed():
    value, error, usage = ollama_typed([], TypedReply, post=lambda *_args, **_kwargs: Response({
        "message": {"content": '{"intent":"market_filter","sql":"DROP TABLE entries"}'},
    }))
    assert value is None
    assert error
    assert usage == {}


def test_ollama_default_model_is_8b(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    assert ollama_model() == "llama3.1:8b"


def test_ollama_role_model_falls_back_to_legacy_setting(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "local-default")
    monkeypatch.delenv("OLLAMA_ANALYST_MODEL", raising=False)
    assert ollama_role_model("analyst") == "local-default"
    monkeypatch.setenv("OLLAMA_ANALYST_MODEL", "local-analyst")
    assert ollama_role_model("analyst") == "local-analyst"


def test_ollama_status_detects_installed_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    status = ollama_status(get=lambda *_args, **_kwargs: Response({"models": [{"name": "llama3.2:3b"}]}))

    assert status["available"] is True
    assert status["running"] is True
    assert status["model"] == "llama3.2:3b"
    assert status["vision_available"] is False


def test_ollama_status_detects_vision_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_VISION_MODEL", "llama3.2-vision:11b")
    status = ollama_status(get=lambda *_args, **_kwargs: Response({"models": [{"name": "llama3.2-vision:11b"}]}))

    assert status["vision_available"] is True
    assert status["vision_model"] == "llama3.2-vision:11b"


def test_ollama_chat_uses_local_non_streaming_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"message": {"content": "Use the verified two-leg card."}})

    text, error = ollama_chat([{"role": "user", "content": "Review"}], post=post)

    assert error is None
    assert text == "Use the verified two-leg card."
    assert calls[0][0].endswith("/api/chat")
    assert calls[0][1]["json"]["stream"] is False
    assert calls[0][1]["json"]["options"]["temperature"] == 0.0


def test_ollama_chat_reports_usage_without_response_text(monkeypatch):
    usage = []
    text, error = ollama_chat(
        [{"role": "user", "content": "Synthetic prompt"}],
        usage_callback=usage.append,
        post=lambda *_args, **_kwargs: Response({
            "message": {"content": "Synthetic answer"},
            "load_duration": 100, "prompt_eval_count": 12, "eval_count": 4,
        }),
    )
    assert error is None
    assert text == "Synthetic answer"
    assert usage == [{"load_duration": 100, "prompt_eval_count": 12, "eval_count": 4}]


def test_ollama_usage_callback_failure_does_not_break_answer():
    def fail(_usage):
        raise RuntimeError("telemetry failed")

    text, error = ollama_chat(
        [], usage_callback=fail,
        post=lambda *_args, **_kwargs: Response({"message": {"content": "Still answered"}, "eval_count": 2}),
    )
    assert error is None
    assert text == "Still answered"


def test_role_budgets_and_keep_alive_are_bounded(monkeypatch):
    monkeypatch.setenv("OLLAMA_PLANNER_NUM_PREDICT", "999999")
    monkeypatch.setenv("OLLAMA_ANALYST_NUM_PREDICT", "invalid")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "broken")
    assert ollama_predict_limit("planner") == 512
    assert ollama_predict_limit("analyst") == 240
    assert ollama_keep_alive() == "10m"

    monkeypatch.setenv("OLLAMA_ANALYST_NUM_PREDICT", "480")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "2m")
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs["json"])
        return Response({"message": {"content": "Grounded answer"}})

    assert ollama_chat([{"role": "user", "content": "Check"}], post=post)[0] == "Grounded answer"
    assert calls[0]["keep_alive"] == "2m"
    assert calls[0]["options"]["num_predict"] == 480


def test_typed_planner_uses_role_budget(monkeypatch):
    monkeypatch.setenv("OLLAMA_PLANNER_NUM_PREDICT", "128")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "0")
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs["json"])
        return Response({"message": {"content": '{"intent":"market_filter"}'}})

    assert ollama_typed([], TypedReply, post=post)[0] is not None
    assert calls[0]["options"]["num_predict"] == 128
    assert calls[0]["keep_alive"] == "0"


def test_ollama_structured_passes_schema_and_parses_json():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}

    def post(_url, **kwargs):
        assert kwargs["json"]["format"] == schema
        return Response({"message": {"content": '{"answer":"grounded"}'}})

    value, error = ollama_structured([{"role": "user", "content": "Review"}], schema, post=post)

    assert error is None
    assert value == {"answer": "grounded"}


def test_ollama_vision_sends_base64_image():
    calls = []

    def post(_url, **kwargs):
        calls.append(kwargs["json"])
        return Response({"message": {"content": '{"props":[]}'}})

    value, error = ollama_vision_structured(
        b"image-bytes", "Read it", {"type": "object"}, model="vision-test", post=post,
    )

    assert error is None
    assert value == {"props": []}
    assert calls[0]["model"] == "vision-test"
    assert calls[0]["messages"][0]["images"]


def test_ollama_chat_explains_missing_local_service():
    def post(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    text, error = ollama_chat([{"role": "user", "content": "Review"}], post=post)

    assert text is None
    assert "not running" in error


def test_ollama_grounding_guard_rejects_invented_opponent_defense():
    assert _unsupported_ollama_matchup_claim("Minnesota has a stronger defense.") is True
    assert _unsupported_ollama_matchup_claim("The opponent's performance is based on one game.") is True
    assert _unsupported_ollama_matchup_claim("The player averaged 23.5 points in two verified games.") is False


def test_ollama_grounding_guard_requires_exact_selected_player_identities():
    suggestions = [{
        "entry": {
            "props": [
                {"player": "Temi Fágbénlé"},
                {"player": "Diamond Miller"},
            ],
        },
    }]

    assert _ollama_card_identity_mismatch(
        "Temi Fàgbènni and Diamond Miller are the selected legs.", suggestions,
    ) is True
    assert _ollama_card_identity_mismatch(
        "Temi Fagbenle and Diamond Miller are the selected legs.", suggestions,
    ) is False
