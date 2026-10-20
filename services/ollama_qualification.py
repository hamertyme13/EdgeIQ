"""Read explicitly approved local-model roles; benchmark output cannot approve itself."""

from __future__ import annotations

import json
import os
import platform
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path

BENCHMARK_VERSION = "copilot-fixed-v2"


def current_hardware_profile() -> str:
    host_tag = sha256(platform.node().encode("utf-8")).hexdigest()[:12]
    return f"{platform.system()}-{platform.machine()}-{host_tag}"


def approved_role_model(role: str) -> str | None:
    if role not in {"planner", "analyst"}:
        return None
    if os.getenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    location = os.getenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", "").strip()
    if not location:
        return None
    try:
        registry = json.loads(Path(location).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        return None
    records = registry.get("qualified_models")
    record = records.get(role) if isinstance(records, dict) else None
    if not isinstance(record, dict):
        return None
    model = record.get("model")
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        return None
    if record.get("benchmark_version") != BENCHMARK_VERSION:
        return None
    if not all(record.get(key) is True for key in (
        "automatic_gates_passed", "fact_audit_passed", "baseline_comparison_passed", "manually_approved",
    )):
        return None
    if not isinstance(record.get("approved_by"), str) or not record["approved_by"].strip():
        return None
    if record.get("hardware_profile") != current_hardware_profile():
        return None
    digest = record.get("benchmark_report_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    report_path = record.get("benchmark_report_path")
    if not isinstance(report_path, str) or not Path(report_path).is_absolute():
        return None
    try:
        with Path(report_path).open("rb") as source:
            raw = source.read(1_000_001)
        if len(raw) > 1_000_000 or sha256(raw).hexdigest() != digest:
            return None
        report = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict) or report.get("benchmark_version") != BENCHMARK_VERSION:
        return None
    if report.get("model") != model or report.get("hardware_profile") != record["hardware_profile"]:
        return None
    roles = report.get("roles")
    role_result = roles.get(role) if isinstance(roles, dict) else None
    if not isinstance(role_result, dict) or role_result.get("automatic_gates_passed") is not True:
        return None
    repetitions = role_result.get("repetitions")
    if not isinstance(repetitions, int) or repetitions < 3 or role_result.get("benchmark_version") != BENCHMARK_VERSION:
        return None
    if role_result.get("cases_run") != 20 or role_result.get("combined_suite_cases") != 40:
        return None
    attempts = role_result.get("attempts")
    if not isinstance(attempts, int) or attempts < 20 * repetitions or role_result.get("security_passed") is not True:
        return None
    fidelity = role_result.get("fidelity_rate")
    overall = role_result.get("overall_rate")
    if (not isinstance(fidelity, (int, float)) or not isinstance(overall, (int, float))
            or fidelity < 0.95 or overall < 0.9):
        return None
    try:
        approved_at = datetime.fromisoformat(record["approved_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if approved_at.tzinfo is None:
        return None
    return model.strip()
