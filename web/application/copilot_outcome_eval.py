"""Read-only, pregame-only analyst evaluation against settled prediction records."""

from __future__ import annotations

from collections.abc import Callable
from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import isfinite
from statistics import mean

from repository.database import SessionLocal
from repository.models.prediction_record_model import PredictionRecordModel
from web.application.copilot_service import _grounded_answer


def _utc(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def eligible_cases(rows: list[dict], *, limit: int = 12) -> list[dict]:
    """Keep independent, verified predictions and sample recent cases across sports."""
    valid = []
    for row in rows:
        predicted, game, features, settled = (_utc(row.get(key)) for key in (
            "predicted_at", "game_time", "feature_as_of", "settled_at",
        ))
        if not (predicted and game and features and settled and features <= predicted < game <= settled):
            continue
        if row.get("legacy_quarantined") or row.get("outcome") not in {"Win", "Loss"}:
            continue
        if row.get("outcome_source") not in {"espn", "mlb_statsapi", "nba_api", "pandascore", "statshawk"}:
            continue
        if not row.get("player_identity_id") or not row.get("independent_market_key") or not row.get("model_version"):
            continue
        try:
            probability = float(row["probability"])
            line = float(row["line"])
            projection = float(row["projection"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(isfinite(value) for value in (probability, line, projection)) or not 0 <= probability <= 100:
            continue
        valid.append(row)
    valid.sort(key=lambda row: (_utc(row["predicted_at"]), str(row.get("id") or "")))
    independent = {}
    for row in valid:
        independent.setdefault(row["independent_market_key"], row)
    by_sport: dict[str, list[dict]] = defaultdict(list)
    for row in reversed(list(independent.values())):
        by_sport[str(row.get("sport") or "Unknown")].append(row)
    chosen = []
    cap = max(1, min(limit, 50))
    while len(chosen) < cap and any(by_sport.values()):
        for sport in sorted(by_sport):
            if by_sport[sport]:
                chosen.append(by_sport[sport].pop(0))
                if len(chosen) == cap:
                    break
    return sorted(chosen, key=lambda row: _utc(row["predicted_at"]))


def pregame_bundle(row: dict) -> dict:
    """Never include result, actual, settlement time, or postgame evidence in the prompt."""
    snapshot = {
        key: row.get(key) for key in (
            "player", "team", "sport", "stat", "platform", "game", "game_time",
            "direction", "line", "projection", "probability", "projection_source",
            "model_version", "line_offer_type", "feature_as_of", "predicted_at",
        )
    }
    return {
        "intent": "settled_pregame_replay",
        "summary": {"selected": snapshot},
        "citations": [
            {
                "id": "pregame-forecast", "label": "Locked pregame probability_forecast",
                "captured_at": str(row.get("predicted_at") or ""),
                "data": {key: snapshot[key] for key in (
                    "player", "sport", "stat", "direction", "projection", "probability",
                    "projection_source", "model_version", "feature_as_of",
                )},
            },
            {
                "id": "pregame-offer", "label": "Historical pregame provider_market offer",
                "captured_at": str(row.get("predicted_at") or ""),
                "data": {key: snapshot[key] for key in (
                    "player", "sport", "stat", "platform", "game", "game_time",
                    "direction", "line", "line_offer_type",
                )},
            },
        ],
    }


def evaluate_cases(
    rows: list[dict], *, model: str,
    analyst: Callable = _grounded_answer,
    limit: int = 12,
) -> dict:
    cases = eligible_cases(rows, limit=limit)
    results = []
    for row in cases:
        bundle = pregame_bundle(row)
        answer, error = analyst(
            "Explain this pregame prop forecast briefly. State what is known and what is missing; do not claim it won or lost.",
            bundle, model=model,
        )
        body = " ".join(str(value) for key, value in (answer or {}).items() if key != "citations").casefold()
        grounded = bool(answer and not error and (answer.get("citations") or [])
                        and set(answer["citations"]).issubset({"pregame-forecast", "pregame-offer"}))
        outcome_leak = any(phrase in body for phrase in ("this bet won", "this bet lost", "this pick won", "this pick lost"))
        probability = float(row["probability"]) / 100
        observed = int(row["outcome"] == "Win")
        results.append({
            "prediction_id": row.get("id"), "sport": row.get("sport"), "stat": row.get("stat"),
            "model_version": row.get("model_version"), "predicted_at": str(row.get("predicted_at")),
            "grounded": grounded and not outcome_leak, "outcome_leak": outcome_leak,
            "error": error, "forecast_brier": round((probability - observed) ** 2, 4),
            "outcome": row["outcome"],
        })
    by_sport: dict[str, dict] = {}
    for sport in sorted({row["sport"] for row in results}):
        subset = [row for row in results if row["sport"] == sport]
        by_sport[sport] = {
            "cases": len(subset), "grounded": sum(row["grounded"] for row in subset),
            "grounding_rate": round(mean(row["grounded"] for row in subset), 4),
            "forecast_brier": round(mean(row["forecast_brier"] for row in subset), 4),
        }
    return {
        "model": model, "method": "settled_chronological_pregame_replay",
        "cases": len(results), "grounded": sum(row["grounded"] for row in results),
        "grounding_rate": round(mean(row["grounded"] for row in results), 4) if results else None,
        "forecast_brier": round(mean(row["forecast_brier"] for row in results), 4) if results else None,
        "by_sport": by_sport,
        "rejection_reasons": dict(sorted(Counter(
            row["error"] or ("Outcome leaked" if row["outcome_leak"] else "Missing validated citation")
            for row in results if not row["grounded"]
        ).items())),
        "rows": results, "qualified": False,
        "note": "LLM grounding and the existing statistical forecast are measured separately. No model is promoted.",
    }


def load_settled_cases(*, max_rows: int = 5000) -> list[dict]:
    fields = (
        "id", "player_identity_id", "independent_market_key", "model_version", "legacy_quarantined",
        "outcome_source", "predicted_at", "game_time", "settled_at", "feature_as_of", "probability",
        "line", "projection", "projection_source", "player", "team", "sport", "stat", "platform",
        "game", "direction", "line_offer_type", "outcome",
    )
    with SessionLocal() as session:
        query = session.query(*(getattr(PredictionRecordModel, field) for field in fields))
        records = (query.filter(PredictionRecordModel.outcome.in_(("Win", "Loss")))
                   .order_by(PredictionRecordModel.predicted_at.desc())
                   .limit(max(1, min(max_rows, 5000))).all())
    return [dict(zip(fields, row, strict=True)) for row in records]
