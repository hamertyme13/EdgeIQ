"""PII-free timing and outcome traces for Ask EdgeIQ requests."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable

from services.ollama_client import OLLAMA_USAGE_KEYS

_log = logging.getLogger(__name__)


class CopilotTrace:
    def __init__(self, progress: Callable[[str, str], None] | None = None) -> None:
        self.request_id = f"req_{uuid.uuid4().hex[:12]}"
        self.started = time.perf_counter()
        self.stage_started = self.started
        self.stage = "planning"
        self.durations: dict[str, float] = {}
        self.analyst_usage: dict[str, int | float] = {}
        self.analyst_model_calls = 0
        self.progress_callback = progress

    def record_analyst_usage(self, usage: dict) -> None:
        self.analyst_model_calls += 1
        for key in OLLAMA_USAGE_KEYS:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.analyst_usage[key] = self.analyst_usage.get(key, 0) + value

    def progress(self, stage: str, label: str) -> None:
        now = time.perf_counter()
        if stage != self.stage:
            self.durations[self.stage] = self.durations.get(self.stage, 0.0) + now - self.stage_started
            self.stage = stage
            self.stage_started = now
        if self.progress_callback:
            self.progress_callback(stage, label)

    def finish(self, result: dict | None, error: Exception | None = None) -> None:
        try:
            self._finish(result, error)
        except Exception:
            _log.warning("copilot_trace_emit_failed")

    def _finish(self, result: dict | None, error: Exception | None) -> None:
        now = time.perf_counter()
        self.durations[self.stage] = self.durations.get(self.stage, 0.0) + now - self.stage_started
        result = result or {}
        execution = result.get("execution") or {}
        usage = execution.get("ollama_usage") or {}
        evidence = result.get("evidence_summary") or {}
        citations = result.get("citations") or []
        trace = {
            "request_id": self.request_id,
            "intent": str(result.get("intent") or "unknown"),
            "planner": str(execution.get("planner") or "rules"),
            "model": str(result.get("model") or "none"),
            "fallback": bool(result.get("ai_error") or execution.get("planner") == "rules_fallback"),
            "failed": error is not None,
            "failure_type": type(error).__name__ if error else None,
            "total_ms": round((now - self.started) * 1000, 1),
            "planning_ms": round(self.durations.get("planning", 0.0) * 1000, 1),
            "retrieval_ms": round(self.durations.get("retrieval", 0.0) * 1000, 1),
            "analysis_ms": round(self.durations.get("analysis", 0.0) * 1000, 1),
            "grounding_ms": round(self.durations.get("grounding", 0.0) * 1000, 1),
            "tool_calls": int(execution.get("tool_calls") or 0),
            "citation_count": len(citations),
            "evidence_selected": int(evidence.get("citation_count") or 0),
            "analyst_model_calls": self.analyst_model_calls,
            "ollama": {
                "planner": {key: usage[key] for key in OLLAMA_USAGE_KEYS if key in usage},
                "analyst": self.analyst_usage,
            },
        }
        _log.info("copilot_trace %s", json.dumps(trace, separators=(",", ":")))
