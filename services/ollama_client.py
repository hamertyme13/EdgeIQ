from __future__ import annotations

import os
from collections.abc import Callable

import requests

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"


def ollama_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL).strip().rstrip("/") or DEFAULT_OLLAMA_URL


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL


def ollama_enabled() -> bool:
    return os.getenv("OLLAMA_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def ollama_status(*, get: Callable[..., requests.Response] = requests.get) -> dict:
    if not ollama_enabled():
        return {"configured": False, "available": False, "model": ollama_model(), "models": [], "note": "Ollama is disabled."}
    try:
        response = get(f"{ollama_url()}/api/tags", timeout=1.5)
        response.raise_for_status()
        data = response.json()
        models = [str(row.get("name") or "") for row in data.get("models", []) if row.get("name")]
        selected = ollama_model()
        installed = selected in models or any(name.split(":", 1)[0] == selected.split(":", 1)[0] for name in models)
        return {
            "configured": True,
            "available": installed,
            "running": True,
            "model": selected,
            "models": models,
            "note": (
                f"Ollama is ready with {selected}."
                if installed
                else f"Ollama is running, but {selected} is not installed. Run: ollama pull {selected}"
            ),
        }
    except requests.RequestException:
        return {
            "configured": True,
            "available": False,
            "running": False,
            "model": ollama_model(),
            "models": [],
            "note": "Ollama is not running. Open Ollama before using Ask EdgeIQ.",
        }


def ollama_chat(
    messages: list[dict],
    *,
    timeout: int = 45,
    post: Callable[..., requests.Response] = requests.post,
) -> tuple[str | None, str | None]:
    if not ollama_enabled():
        return None, "Ollama is disabled."
    model = ollama_model()
    try:
        response = post(
            f"{ollama_url()}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "10m",
                "options": {"temperature": 0.0, "num_predict": 420},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = str((response.json().get("message") or {}).get("content") or "").strip()
        if not content:
            return None, "Ollama returned an empty response. EdgeIQ used its rules-based review instead."
        return content, None
    except requests.Timeout:
        return None, "Ollama took too long to respond. EdgeIQ used its rules-based review instead."
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", "unknown")
        if status == 404:
            return None, f"The local model is not installed. Run: ollama pull {model}"
        return None, "Ollama could not complete the review. EdgeIQ used its rules-based review instead."
    except requests.RequestException:
        return None, "Ollama is not running. Open Ollama and try Ask EdgeIQ again."
