from __future__ import annotations

import requests

from services.ollama_client import ollama_chat, ollama_model, ollama_status, ollama_structured, ollama_vision_structured
from web.app import _unsupported_ollama_matchup_claim


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


def test_ollama_default_model_is_8b(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    assert ollama_model() == "llama3.1:8b"


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
