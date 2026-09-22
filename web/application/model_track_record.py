"""Bounded consumer view of the existing locked prediction ledger."""
from datetime import UTC, datetime
from math import isfinite

from repository.database import SessionLocal
from repository.models.prediction_record_model import PredictionRecordModel
from web.application.player_performance import _time, performance_summary


def summarize_track_record(rows: list[dict]) -> dict:
    locked = []
    for row in rows:
        predicted, game, features = (_time(row.get(key)) for key in ("predicted_at", "game_time", "feature_as_of"))
        try:
            probability = float(row["probability"])
        except (ValueError, TypeError, KeyError):
            continue
        if (not row.get("legacy_quarantined") and row.get("player_identity_id")
                and row.get("independent_market_key") and row.get("model_version")
                and "legacy" not in row["model_version"].lower()
                and predicted and game and features and features <= predicted < game
                and isfinite(probability) and 0 <= probability <= 100):
            locked.append(row)
    locked.sort(key=lambda row: _time(row["predicted_at"]) or datetime.min.replace(tzinfo=UTC))
    # Separate models/providers/directions intentionally; never call their sum
    # the number of unique games or independent underlying sporting outcomes.
    unique: dict[tuple, dict] = {}
    for row in locked:
        key = (row["model_version"], row.get("platform"), row.get("direction"), row["independent_market_key"])
        unique.setdefault(key, row)
    summary = performance_summary(list(unique.values()))
    pushes = 0
    for row in unique.values():
        settled, game = _time(row.get("settled_at")), _time(row.get("game_time"))
        try:
            valid_push = isfinite(float(row["actual"])) and isfinite(float(row["line"])) and float(row["actual"]) == float(row["line"])
        except (ValueError, TypeError, KeyError):
            valid_push = False
        if (row.get("result") == "Push" and row.get("outcome_source") in {"espn", "mlb_statsapi", "nba_api", "pandascore"}
                and settled and game and settled >= game and valid_push):
            pushes += 1
    decisions = sum(item["settled_predictions"] for item in summary["versions"])
    return {**summary, "locked_predictions": len(unique), "settled_predictions": decisions + pushes,
            "wins": sum(item["wins"] for item in summary["versions"]),
            "losses": sum(item["losses"] for item in summary["versions"]), "pushes": pushes,
            "unresolved_or_excluded": len(unique) - decisions - pushes,
            "clv": None, "roi": None, "score_buckets": None,
            "counting_note": "Counts are deduplicated within each model/provider/direction, not independent across models or providers."}


def model_track_record(sport: str = "", provider: str = "", stat: str = "", direction: str = "", model_version: str = "") -> dict:
    fields = ("id", "player_identity_id", "independent_market_key", "model_version", "legacy_quarantined",
              "outcome_source", "predicted_at", "game_time", "settled_at", "feature_as_of", "probability",
              "actual", "line", "direction", "platform", "outcome")
    with SessionLocal() as session:
        query = session.query(*(getattr(PredictionRecordModel, field) for field in fields)).filter(
            PredictionRecordModel.legacy_quarantined.is_(False))
        for field, value in (("sport", sport.upper()), ("platform", provider), ("stat", stat),
                             ("direction", direction), ("model_version", model_version)):
            if value:
                query = query.filter(getattr(PredictionRecordModel, field) == value)
        records = query.order_by(PredictionRecordModel.predicted_at.asc(), PredictionRecordModel.id.asc()).limit(5001).all()
    rows = [dict(zip(fields, row, strict=True)) for row in records[:5000]]
    for row in rows:
        row["result"] = row.pop("outcome")
    return {**summarize_track_record(rows), "records_examined": len(rows), "truncated": len(records) > 5000,
            "window_note": "First 5,000 matching ledger records in chronological order. Narrow filters if the window is truncated."}
