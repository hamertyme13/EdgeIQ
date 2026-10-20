from __future__ import annotations

import json
from hashlib import sha256

from scripts import qualify_ollama_model
from services import ollama_qualification
from services.ollama_client import ollama_role_model
from services.ollama_qualification import approved_role_model


def _registry(tmp_path, *, passed=True):
    report = {
        "benchmark_version": "copilot-fixed-v2", "model": "reviewed-model",
        "hardware_profile": "Test-arm64",
        "roles": {"planner": {
            "benchmark_version": "copilot-fixed-v2", "repetitions": 3,
            "automatic_gates_passed": passed, "cases_run": 20,
            "combined_suite_cases": 40, "attempts": 60,
            "security_passed": passed, "fidelity_rate": 1.0,
            "overall_rate": 1.0,
        }},
    }
    report_path = tmp_path / "report.json"
    raw = (json.dumps(report) + "\n").encode()
    report_path.write_bytes(raw)
    record = {
        "model": "reviewed-model", "benchmark_version": "copilot-fixed-v2",
        "benchmark_report_path": str(report_path),
        "benchmark_report_sha256": sha256(raw).hexdigest(),
        "hardware_profile": "Test-arm64", "automatic_gates_passed": True,
        "fact_audit_passed": True, "baseline_comparison_passed": True,
        "manually_approved": True, "approved_by": "Reviewer",
        "approved_at": "2026-10-14T12:00:00+00:00",
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"schema_version": 1, "qualified_models": {"planner": record}}))
    return registry_path, report_path, record


def test_registry_is_opt_in_and_explicit_setting_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_qualification, "current_hardware_profile", lambda: "Test-arm64")
    registry, _report, _record = _registry(tmp_path)
    monkeypatch.setenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", str(registry))
    monkeypatch.setenv("OLLAMA_MODEL", "existing-model")
    monkeypatch.delenv("OLLAMA_PLANNER_MODEL", raising=False)
    assert approved_role_model("planner") is None
    assert ollama_role_model("planner") == "existing-model"
    monkeypatch.setenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "true")
    assert ollama_role_model("planner") == "reviewed-model"
    assert ollama_role_model("analyst") == "existing-model"
    monkeypatch.setenv("OLLAMA_PLANNER_MODEL", "explicit-model")
    assert ollama_role_model("planner") == "explicit-model"


def test_registry_rejects_tampered_report_or_missing_review(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_qualification, "current_hardware_profile", lambda: "Test-arm64")
    registry, report, record = _registry(tmp_path)
    monkeypatch.setenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", str(registry))
    monkeypatch.setenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "true")
    assert approved_role_model("planner") == "reviewed-model"
    report.write_text("{}")
    assert approved_role_model("planner") is None
    registry, _report, record = _registry(tmp_path)
    record["fact_audit_passed"] = False
    registry.write_text(json.dumps({"schema_version": 1, "qualified_models": {"planner": record}}))
    assert approved_role_model("planner") is None


def test_registry_rejects_failed_or_malformed_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_qualification, "current_hardware_profile", lambda: "Test-arm64")
    registry, _report, record = _registry(tmp_path, passed=False)
    monkeypatch.setenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", str(registry))
    monkeypatch.setenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "true")
    assert approved_role_model("planner") is None
    record["benchmark_version"] = "old-version"
    registry.write_text(json.dumps({"schema_version": 1, "qualified_models": {"planner": record}}))
    assert approved_role_model("planner") is None
    registry.write_text("not json")
    assert approved_role_model("planner") is None


def test_registry_rejects_incomplete_case_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_qualification, "current_hardware_profile", lambda: "Test-arm64")
    registry, report_path, record = _registry(tmp_path)
    monkeypatch.setenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", str(registry))
    monkeypatch.setenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "true")
    report = json.loads(report_path.read_text())
    report["roles"]["planner"]["cases_run"] = 4
    raw = (json.dumps(report) + "\n").encode()
    report_path.write_bytes(raw)
    record["benchmark_report_sha256"] = sha256(raw).hexdigest()
    registry.write_text(json.dumps({"schema_version": 1, "qualified_models": {"planner": record}}))
    assert approved_role_model("planner") is None


def test_registry_rejects_pre_v2_report_even_with_new_record(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_qualification, "current_hardware_profile", lambda: "Test-arm64")
    registry, report_path, record = _registry(tmp_path)
    monkeypatch.setenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", str(registry))
    monkeypatch.setenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "true")
    report = json.loads(report_path.read_text())
    report["benchmark_version"] = "copilot-fixed-v1"
    raw = (json.dumps(report) + "\n").encode()
    report_path.write_bytes(raw)
    record["benchmark_report_sha256"] = sha256(raw).hexdigest()
    registry.write_text(json.dumps({"schema_version": 1, "qualified_models": {"planner": record}}))
    assert approved_role_model("planner") is None


def test_registry_rejects_other_hardware(tmp_path, monkeypatch):
    registry, _report, _record = _registry(tmp_path)
    monkeypatch.setenv("EDGEIQ_OLLAMA_QUALIFICATION_FILE", str(registry))
    monkeypatch.setenv("EDGEIQ_OLLAMA_USE_QUALIFIED_ROLES", "true")
    monkeypatch.setattr(ollama_qualification, "current_hardware_profile", lambda: "Other-x86_64")
    assert approved_role_model("planner") is None


def test_combined_report_does_not_promote_model(monkeypatch):
    monkeypatch.setattr(qualify_ollama_model, "run_preview", lambda role, model, repetitions: {
        "role": role, "model": model, "repetitions": repetitions, "automatic_gates_passed": True,
    })
    report = qualify_ollama_model.build_report("test-model")
    assert set(report["roles"]) == {"planner", "analyst"}
    assert report["qualified"] is False
    assert report["roles"]["planner"]["repetitions"] == 3
