from __future__ import annotations

import json

from analytics.backtesting import backtest_summary
from analytics.grouped_validation import grouped_rolling_validation
from analytics.model_registry import model_registry
from analytics.release_validation import validation_readiness
from repository.bet_repository import BetRepository
from repository.repositories.board_offer_repository import BoardOfferRepository
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository
from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository
from services.dashboard import get_dashboard
from utils.time import iso_utc


def performance_payload() -> dict:
    stats = get_dashboard()
    return {
        "bankroll_curve": stats.get("bankroll_curve", []),
        "by_sport": stats.get("by_sport", {}),
        "by_stat": stats.get("by_stat", {}),
        "by_platform": stats.get("by_platform", {}),
        "entries": stats.get("entries", {}),
        "monthly_profit": stats.get("monthly_profit", {}),
        "summary": stats,
    }


def backtest_payload(clv: dict) -> dict:
    entries = EntryRepository.all()
    PredictionLedgerRepository.backfill_legacy_quarantine()
    prediction_rows = PredictionLedgerRepository.evidence_rows(include_legacy=False)
    entry_ids = {int(entry.get("id") or 0) for entry in entries}
    prediction_rows = [
        row for row in prediction_rows
        if int(row.get("entry_id") or 0) in entry_ids
    ]
    if not all(
        prop.get("entry_prop_id")
        for entry in entries
        for prop in (entry.get("props") or [])
    ):
        prediction_rows = []
    payload = backtest_summary(
        BetRepository().get_all(),
        entries,
        prediction_rows=prediction_rows or None,
    )
    readiness = payload.get("validation_readiness") or {}
    prediction_summary = PredictionLedgerRepository.summary()
    grouped_validation = grouped_rolling_validation(prediction_rows)
    payload["grouped_validation"] = grouped_validation
    payload["validation_readiness"] = validation_readiness(
        entries,
        [
            row
            for dimension_rows in (readiness.get("dimensions") or {}).values()
            for row in dimension_rows
        ],
        readiness.get("calibration_error") or {},
        payload.get("holdout_validation") or {},
        payload.get("walk_forward_validation") or {},
        clv,
        prediction_rows=prediction_rows,
        grouped_validation=grouped_validation,
        prediction_summary=prediction_summary,
    )
    payload["prediction_ledger"] = prediction_summary
    payload["complete_board_evidence"] = BoardOfferRepository.evidence_report()
    payload["shadow_evaluation"] = ModelRehabilitationRepository.shadow_status(
        prediction_rows,
        validation={
            "closing_line_value": clv,
            "holdout": payload.get("holdout_validation") or {},
        },
    )
    return payload


def model_health_payload(ai: dict) -> dict:
    versioned_predictions = PredictionLedgerRepository.evidence_rows(include_legacy=False)
    backtest_data = backtest_summary(
        BetRepository().get_all(),
        EntryRepository.all(),
        prediction_rows=versioned_predictions,
    )
    entry_confidence = backtest_data.get("entries", {}).get("confidence", {})
    calibration = backtest_data.get("calibration", [])
    scorecard = backtest_data.get("scorecard", {})
    holdout = backtest_data.get("holdout_validation", {})
    grouped_validation = grouped_rolling_validation(versioned_predictions)
    calibrated_rows = sum(bucket.get("bets", 0) for bucket in calibration)
    avg_error = (
        sum(abs(bucket.get("error", 0.0)) * bucket.get("bets", 0) for bucket in calibration)
        / calibrated_rows
        if calibrated_rows
        else 0.0
    )
    settled_entries = backtest_data.get("entries", {}).get("count", 0)
    dashboard_stats = get_dashboard()
    source_score = min(100.0, 35.0 + (calibrated_rows * 2.5) + (settled_entries * 3.0))
    calibration_score = max(0.0, 100.0 - (avg_error * 2.0)) if calibrated_rows else 45.0
    confidence_edge = abs(float(entry_confidence.get("edge") or 0.0))
    confidence_score = max(0.0, 100.0 - (confidence_edge * 2.0)) if settled_entries else 50.0
    ai_score = 100.0 if ai["configured"] and ai["key_format_ok"] else 55.0
    recommendation_accuracy = dashboard_stats.get("recommendation_accuracy", {})
    rec_accuracy = float(recommendation_accuracy.get("accuracy") or 0.0)
    accuracy_score = rec_accuracy if recommendation_accuracy.get("tracked") else 50.0
    raw_trust_score = round(
        (calibration_score * 0.34)
        + (confidence_score * 0.22)
        + (source_score * 0.18)
        + (ai_score * 0.12)
        + (accuracy_score * 0.14),
        1,
    )
    scorecard_value = scorecard.get("score")
    scorecard_score = raw_trust_score if scorecard_value is None else float(scorecard_value)
    trust_score = round(min(raw_trust_score, scorecard_score), 1)
    verdict = str(scorecard.get("verdict") or "")
    paid_entry_mode = "enabled"
    if scorecard_score < 55 or verdict in {"Model needs calibration", "Collect more samples"}:
        paid_entry_mode = "paper_first"
    if float(scorecard.get("roi") or 0.0) < 0:
        paid_entry_mode = "paper_first"
    if not holdout.get("ready") or not holdout.get("passed"):
        paid_entry_mode = "paper_first"
    if not grouped_validation.get("ready") or not grouped_validation.get("passed"):
        paid_entry_mode = "paper_first"
    if int(grouped_validation.get("unique_predictions") or 0) < 500:
        paid_entry_mode = "paper_first"
    if trust_score >= 78:
        status = "Strong"
    elif trust_score >= 62:
        status = "Usable"
    elif trust_score >= 48:
        status = "Learning"
    else:
        status = "Needs Data"
    if paid_entry_mode != "enabled":
        status = "Needs Calibration" if calibrated_rows or settled_entries else "Learning"

    return {
        "trust_score": trust_score,
        "status": status,
        "paid_entry_mode": paid_entry_mode,
        "scorecard": scorecard,
        "holdout_validation": holdout,
        "grouped_validation": grouped_validation,
        "prediction_ledger": PredictionLedgerRepository.summary(),
        "model_registry": model_registry(),
        "settled_entries": settled_entries,
        "calibrated_picks": calibrated_rows,
        "average_calibration_error": round(avg_error, 1),
        "actual_vs_confidence_edge": entry_confidence.get("edge", 0.0),
        "openai": ai,
        "recommendation_accuracy": recommendation_accuracy,
        "components": {
            "calibration": round(calibration_score, 1),
            "confidence_alignment": round(confidence_score, 1),
            "data_depth": round(source_score, 1),
            "ai_readiness": round(ai_score, 1),
            "recommendation_accuracy": round(accuracy_score, 1),
            "scorecard": round(scorecard_score, 1),
        },
        "next_steps": model_health_next_steps(
            calibrated_rows,
            settled_entries,
            ai,
            avg_error,
            scorecard=scorecard,
            holdout=holdout,
            grouped_validation=grouped_validation,
            recommendation_accuracy=recommendation_accuracy,
        ),
    }


def model_health_next_steps(
    calibrated_rows: int,
    settled_entries: int,
    ai: dict,
    avg_error: float,
    *,
    scorecard: dict | None = None,
    holdout: dict | None = None,
    grouped_validation: dict | None = None,
    recommendation_accuracy: dict | None = None,
) -> list[str]:
    scorecard = scorecard or {}
    holdout = holdout or {}
    grouped_validation = grouped_validation or {}
    recommendation_accuracy = recommendation_accuracy or {}
    steps = []
    if float(scorecard.get("score") or 0.0) <= 0:
        steps.append("Keep paid sizing minimal until the scorecard clears its validation gates.")
    if not holdout.get("ready") or not holdout.get("passed"):
        steps.append("Collect enough independent settled predictions to pass holdout validation.")
    if not grouped_validation.get("ready") or not grouped_validation.get("passed"):
        steps.append("Continue paper sampling across sport and stat segments for rolling validation.")
    if recommendation_accuracy.get("tracked") and float(recommendation_accuracy.get("accuracy") or 0.0) < 40:
        steps.append("Review recommendation misses before releasing additional paid cards.")
    if calibrated_rows < 25:
        steps.append("Upload or import more betting history to strengthen confidence calibration.")
    if settled_entries < 10:
        steps.append("Settle more EdgeIQ-recommended entries so the model can learn from its own calls.")
    if not (ai.get("configured") and ai.get("key_format_ok")):
        steps.append("Connect a valid OpenAI API key for richer reasoning and screenshot extraction.")
    if avg_error > 15:
        steps.append("Review high-confidence misses in Performance before increasing bet size.")
    return steps or ["Model inputs look healthy. Keep logging results to preserve calibration."]


def accuracy_lab_payload() -> dict:
    entries = EntryRepository.all()
    settled = [
        entry
        for entry in entries
        if entry.get("status") == "Settled"
        and entry.get("result") in {"Win", "Loss", "Push"}
    ]
    audits = [
        _safe_json_loads(entry.get("audit_snapshot", ""))
        for entry in entries
        if entry.get("audit_snapshot")
    ]
    return {
        "summary": {
            "settled_entries": len(settled),
            "audit_snapshots": len(audits),
            "recommended_settled": sum(
                1 for entry in settled if entry.get("recommended_by_app")
            ),
        },
        "by_grade": EntryRepository._group_by_key(
            settled,
            lambda entry: entry.get("grade") or "Ungraded",
        ),
        "by_sport": EntryRepository._group_by_key(
            settled,
            EntryRepository._primary_sport,
        ),
        "by_platform": EntryRepository._group_by_key(
            settled,
            lambda entry: entry.get("platform") or "Unknown",
        ),
        "confidence_buckets": accuracy_confidence_rows(settled),
        "audit_trail": [
            {
                "entry_id": entry["id"],
                "placed_at": iso_utc(entry.get("placed_at")),
                "result": entry.get("result", ""),
                "grade": entry.get("grade", ""),
                "line_snapshot_count": len(
                    _safe_json_loads(entry.get("audit_snapshot", "")).get("props", [])
                ),
                "recommendation": _safe_json_loads(
                    entry.get("audit_snapshot", "")
                ).get("recommendation", {}),
            }
            for entry in entries[:20]
            if entry.get("audit_snapshot")
        ],
    }


def accuracy_confidence_rows(entries: list[dict]) -> list[dict]:
    buckets = [
        ("0-49", 0, 49.999),
        ("50-59", 50, 59.999),
        ("60-69", 60, 69.999),
        ("70-100", 70, 100),
    ]
    rows = []
    for label, low, high in buckets:
        bucket = [
            entry
            for entry in entries
            if low <= float(entry.get("average_confidence") or 0) <= high
            and entry.get("result") in {"Win", "Loss"}
        ]
        wins = sum(1 for entry in bucket if entry.get("result") == "Win")
        rows.append(
            {
                "label": label,
                "entries": len(bucket),
                "wins": wins,
                "losses": len(bucket) - wins,
                "win_pct": round((wins / len(bucket) * 100) if bucket else 0.0, 1),
                "avg_confidence": (
                    round(
                        sum(
                            float(entry.get("average_confidence") or 0)
                            for entry in bucket
                        )
                        / len(bucket),
                        1,
                    )
                    if bucket
                    else 0.0
                ),
            }
        )
    return rows


def _safe_json_loads(value: str) -> dict:
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
