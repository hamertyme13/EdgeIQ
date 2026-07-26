from __future__ import annotations

from analytics.prediction_evidence import deduplicate_outcomes

RELEASE_NAME = "EdgeIQ v2.1 - Validation and Reliability"


def validation_readiness(
    entries: list[dict],
    segments: list[dict],
    calibration_summary: dict,
    holdout: dict,
    walk_forward: dict,
    clv: dict | None = None,
    prediction_rows: list[dict] | None = None,
    grouped_validation: dict | None = None,
) -> dict:
    settled = [
        entry
        for entry in entries
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push"}
    ]
    paper_entries = [
        entry for entry in settled
        if str(entry.get("entry_mode") or "real").lower() == "paper"
    ]
    raw_settled_props = [
        prop
        for entry in settled
        for prop in entry.get("props") or []
        if prop.get("final_result") in {"Win", "Loss", "Push"}
        and str(prop.get("final_source") or "").lower()
        not in {"", "unknown", "unmatched", "projection_estimate"}
    ]
    has_prediction_ledger = prediction_rows is not None
    prediction_rows = prediction_rows or []
    versioned_rows = [
        row for row in prediction_rows
        if row.get("result") in {"Win", "Loss", "Push"}
        and not row.get("legacy_quarantined")
        and str(row.get("outcome_source") or "").lower()
        not in {"", "unknown", "unmatched", "projection_estimate"}
    ]
    settled_props = deduplicate_outcomes(
        versioned_rows if has_prediction_ledger else raw_settled_props
    )
    grouped_validation = grouped_validation or {}
    dimensions = {
        dimension: [
            row for row in segments
            if row.get("type") == segment_type
        ]
        for dimension, segment_type in (
            ("confidence_bucket", "Confidence"),
            ("grade", "Grade"),
            ("sport", "Sport"),
            ("stat", "Stat"),
            ("provider", "Platform"),
        )
    }
    clv = clv or {}
    gates = [
        _count_gate("Settled paper entries", len(paper_entries), 100),
        _count_gate("Independent versioned props", len(settled_props), 500),
        _boolean_gate(
            "Segmented accuracy",
            all(dimensions[name] for name in dimensions),
            "Confidence, grade, sport, stat, and provider tables must all contain settled outcomes.",
        ),
        _boolean_gate(
            "Chronological holdout",
            bool(holdout.get("ready") and holdout.get("passed")),
            holdout.get("message", "Chronological holdout is not ready."),
        ),
        _boolean_gate(
            "Walk-forward validation",
            bool(grouped_validation.get("ready") and grouped_validation.get("passed")),
            grouped_validation.get("message", "Grouped rolling validation is not ready."),
        ),
        _boolean_gate(
            "Closing-line value",
            int(clv.get("tracked_legs") or 0) >= 50,
            f"{int(clv.get('tracked_legs') or 0)}/50 reliable closing-line snapshots.",
        ),
        _boolean_gate(
            "Calibration error",
            int(calibration_summary.get("total") or 0) >= 100
            and float(calibration_summary.get("average_abs_error") or 100.0) <= 10.0,
            (
                f"{int(calibration_summary.get('total') or 0)} calibrated props; "
                f"{float(calibration_summary.get('average_abs_error') or 0.0):.1f} point mean absolute error."
            ),
        ),
    ]
    required_complete = sum(1 for gate in gates if gate["passed"])
    return {
        "release": RELEASE_NAME,
        "status": "validated" if required_complete == len(gates) else "collecting_evidence",
        "passed_gates": required_complete,
        "total_gates": len(gates),
        "progress_pct": round(required_complete / len(gates) * 100, 1),
        "gates": gates,
        "counts": {
            "settled_entries": len(settled),
            "settled_paper_entries": len(paper_entries),
            "settled_props": len(settled_props),
            "raw_settled_props": len(raw_settled_props),
            "versioned_prediction_rows": len(versioned_rows),
            "duplicate_props_excluded": max(
                0,
                len(versioned_rows if has_prediction_ledger else raw_settled_props)
                - len(settled_props),
            ),
        },
        "dimensions": dimensions,
        "closing_line_value": clv,
        "calibration_error": calibration_summary,
        "grouped_validation": grouped_validation,
    }


def _count_gate(label: str, current: int, target: int, stretch_target: int | None = None) -> dict:
    return {
        "label": label,
        "passed": current >= target,
        "current": current,
        "target": target,
        "stretch_target": stretch_target,
        "progress_pct": round(min(100.0, current / target * 100), 1) if target else 100.0,
        "detail": (
            f"{current}/{target} required"
            + (f"; {stretch_target} preferred" if stretch_target else "")
        ),
    }


def _boolean_gate(label: str, passed: bool, detail: str) -> dict:
    return {
        "label": label,
        "passed": bool(passed),
        "current": 1 if passed else 0,
        "target": 1,
        "stretch_target": None,
        "progress_pct": 100.0 if passed else 0.0,
        "detail": detail,
    }
