from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from contextlib import suppress
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

from services.ollama_qualification import approved_role_model
from utils.config_bounds import bounded_env_int

PlanT = TypeVar("PlanT", bound=BaseModel)
OLLAMA_USAGE_KEYS = (
    "total_duration", "load_duration", "prompt_eval_count",
    "prompt_eval_cached_count", "prompt_eval_duration", "eval_count", "eval_duration",
)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_VISION_MODEL = "llama3.2-vision:11b"


def ollama_keep_alive() -> str:
    value = os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip()
    return value if re.fullmatch(r"(?:0|-1|[1-9]\d*(?:ms|s|m|h))", value) else "10m"


def ollama_predict_limit(role: str) -> int:
    defaults = {"planner": (192, 64, 512), "analyst": (240, 128, 1024), "vision": (240, 128, 1024)}
    default, minimum, maximum = defaults.get(role, defaults["analyst"])
    return bounded_env_int(f"OLLAMA_{role.upper()}_NUM_PREDICT", default, minimum, maximum)


def ollama_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL).strip().rstrip("/") or DEFAULT_OLLAMA_URL


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL


def ollama_role_model(role: str) -> str:
    configured = os.getenv(f"OLLAMA_{role.upper()}_MODEL", "").strip()
    return configured or approved_role_model(role) or ollama_model()


def ollama_typed(
    messages: list[dict],
    output_model: type[PlanT],
    *,
    role: str = "planner",
    model: str | None = None,
    timeout: int = 10,
    num_predict: int | None = None,
    post: Callable[..., requests.Response] = requests.post,
) -> tuple[PlanT | None, str | None, dict]:
    if not ollama_enabled():
        return None, "Ollama is disabled.", {}
    payload = {
        "model": model or ollama_role_model(role),
        "messages": messages,
        "stream": False,
        "keep_alive": ollama_keep_alive(),
        "format": output_model.model_json_schema(),
        "options": {"temperature": 0.0, "num_predict": num_predict if num_predict is not None else ollama_predict_limit(role)},
    }
    try:
        response = post(f"{ollama_url()}/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        value = output_model.model_validate_json(str((body.get("message") or {}).get("content") or ""))
        usage = {key: body[key] for key in OLLAMA_USAGE_KEYS if key in body}
        return value, None, usage
    except (ValidationError, ValueError, TypeError):
        return None, "Ollama returned a plan EdgeIQ could not validate.", {}
    except requests.RequestException:
        return None, "Ollama is unavailable; EdgeIQ used its existing analysis.", {}


def ollama_vision_model() -> str:
    return os.getenv("OLLAMA_VISION_MODEL", DEFAULT_OLLAMA_VISION_MODEL).strip() or DEFAULT_OLLAMA_VISION_MODEL


def ollama_enabled() -> bool:
    return os.getenv("OLLAMA_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def ollama_status(*, get: Callable[..., requests.Response] = requests.get) -> dict:
    if not ollama_enabled():
        return {
            "configured": False, "available": False, "model": ollama_model(),
            "vision_model": ollama_vision_model(), "vision_available": False,
            "models": [], "note": "Ollama is disabled.",
        }
    try:
        response = get(f"{ollama_url()}/api/tags", timeout=1.5)
        response.raise_for_status()
        data = response.json()
        models = [str(row.get("name") or "") for row in data.get("models", []) if row.get("name")]
        selected = ollama_model()
        installed = selected in models or any(name.split(":", 1)[0] == selected.split(":", 1)[0] for name in models)
        vision = ollama_vision_model()
        vision_installed = vision in models or any(
            name.split(":", 1)[0] == vision.split(":", 1)[0] for name in models
        )
        return {
            "configured": True,
            "available": installed,
            "running": True,
            "model": selected,
            "vision_model": vision,
            "vision_available": vision_installed,
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
            "vision_model": ollama_vision_model(),
            "vision_available": False,
            "models": [],
            "note": "Ollama is not running. Open Ollama before using Ask EdgeIQ.",
        }


def ollama_chat(
    messages: list[dict],
    *,
    timeout: int = 45,
    model: str | None = None,
    role: str = "analyst",
    format_schema: dict | None = None,
    usage_callback: Callable[[dict], None] | None = None,
    post: Callable[..., requests.Response] = requests.post,
) -> tuple[str | None, str | None]:
    if not ollama_enabled():
        return None, "Ollama is disabled."
    selected_model = model or ollama_model()
    payload = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "keep_alive": ollama_keep_alive(),
        "options": {"temperature": 0.0, "num_predict": ollama_predict_limit(role)},
    }
    if format_schema:
        payload["format"] = format_schema
    try:
        response = post(
            f"{ollama_url()}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        if usage_callback:
            with suppress(Exception):
                usage_callback({key: body[key] for key in OLLAMA_USAGE_KEYS if key in body})
        content = str((body.get("message") or {}).get("content") or "").strip()
        if not content:
            return None, "Ollama returned an empty response. EdgeIQ used its rules-based review instead."
        return content, None
    except requests.Timeout:
        return None, "Ollama took too long to respond. EdgeIQ used its rules-based review instead."
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", "unknown")
        if status == 404:
            return None, f"The local model is not installed. Run: ollama pull {selected_model}"
        return None, "Ollama could not complete the review. EdgeIQ used its rules-based review instead."
    except requests.RequestException:
        return None, "Ollama is not running. Open Ollama and try Ask EdgeIQ again."


def ollama_structured(
    messages: list[dict],
    schema: dict,
    *,
    timeout: int = 60,
    model: str | None = None,
    role: str = "analyst",
    usage_callback: Callable[[dict], None] | None = None,
    post: Callable[..., requests.Response] = requests.post,
) -> tuple[dict | None, str | None]:
    text, error = ollama_chat(
        messages,
        timeout=timeout,
        model=model,
        role=role,
        format_schema=schema,
        usage_callback=usage_callback,
        post=post,
    )
    if not text:
        return None, error
    try:
        value = json.loads(text)
        return (value, None) if isinstance(value, dict) else (None, "Ollama returned the wrong response shape.")
    except json.JSONDecodeError:
        return None, "Ollama returned unreadable structured output. EdgeIQ used its grounded fallback."


def ollama_vision_structured(
    raw: bytes,
    instruction: str,
    schema: dict,
    *,
    timeout: int = 90,
    model: str | None = None,
    post: Callable[..., requests.Response] = requests.post,
) -> tuple[dict | None, str | None]:
    selected_model = model or ollama_vision_model()
    return ollama_structured(
        [{
            "role": "user",
            "content": instruction,
            "images": [base64.b64encode(raw).decode("ascii")],
        }],
        schema,
        timeout=timeout,
        model=selected_model,
        role="vision",
        post=post,
    )
