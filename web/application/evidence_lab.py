"""Descriptive evidence associations from locked, verified prop forecasts."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite

from repository.database import SessionLocal
from repository.models.prediction_record_model import PredictionRecordModel
from utils.stat_normalization import canonical_stat_label

_FINAL_SOURCES = {"espn", "mlb_statsapi", "nba_api", "pandascore", "statshawk"}
_CATEGORIES = (
    "recent_form", "season_baseline", "opponent_context", "minutes", "opportunity",
    "injury", "teammate_status", "weather", "line_movement", "market_consensus",
    "provider_trend", "role", "home_away", "rest",
)
_FIELDS = (
    "independent_market_key", "player_identity_id", "model_version", "platform", "sport", "stat",
    "direction", "line", "actual", "probability", "outcome", "outcome_source", "predicted_at",
    "game_time", "feature_as_of", "settled_at", "feature_snapshot",
)


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _snapshot(value: object) -> dict | None:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) and isinstance(parsed.get("features"), dict) else None


def _categories(snapshot: dict) -> set[str]:
    features = snapshot["features"]
    signals = snapshot.get("evidence_signals") or []
    sources = {
        (str(signal.get("kind") or "").lower(), str(signal.get("source") or "").lower())
        for signal in signals if isinstance(signal, dict)
    }
    found = set()
    if features.get("recent_5_mean") is not None or features.get("last_10_average") is not None:
        found.add("recent_form")
    if features.get("season_average") is not None or features.get("weighted_mean") is not None:
        found.add("season_baseline")
    try:
        opponent_sample = float(features.get("opponent_sample") or 0)
    except (TypeError, ValueError):
        opponent_sample = 0
    if opponent_sample >= 3 and features.get("opponent_mean") is not None:
        found.add("opponent_context")
    workload = features.get("workload_evidence")
    workload = workload if isinstance(workload, dict) else {}
    opportunity = features.get("opportunity_projection")
    opportunity = opportunity if isinstance(opportunity, dict) else {}
    if features.get("expected_minutes") is not None or (workload.get("verified") and "minute" in str(workload.get("metric") or "").lower()):
        found.add("minutes")
    if opportunity.get("verified"):
        found.add("opportunity")
    if features.get("home_away_sample") and features.get("home_away") not in {None, "", "unknown"}:
        found.add("home_away")
    if features.get("rest_days") is not None:
        found.add("rest")
    if features.get("role_status") or features.get("starter_status"):
        found.add("role")
    for kind, source in sources:
        if kind in {"availability", "injury"} or "injur" in source:
            found.add("injury")
        if "teammate" in kind or "teammate" in source:
            found.add("teammate_status")
        if kind == "weather" or "weather" in source:
            found.add("weather")
        if "line movement" in source:
            found.add("line_movement")
        if "consensus" in source:
            found.add("market_consensus")
        if "trend" in source:
            found.add("provider_trend")
    return found


def summarize_evidence_lab(rows: list[dict], *, truncated: bool = False) -> dict:
    """Use the first eligible pregame forecast for each independent market."""
    independent: dict[str, tuple[dict, set[str]]] = {}
    for row in sorted(rows, key=lambda item: _time(item.get("predicted_at")) or datetime.max.replace(tzinfo=UTC)):
        key = str(row.get("independent_market_key") or "")
        version = str(row.get("model_version") or "")
        predicted, game, feature, settled = (_time(row.get(field)) for field in ("predicted_at", "game_time", "feature_as_of", "settled_at"))
        snapshot = _snapshot(row.get("feature_snapshot"))
        if (not key or key in independent or not row.get("player_identity_id") or not version
                or "legacy" in version.lower() or not snapshot
                or predicted is None or game is None or feature is None or settled is None
                or not feature <= predicted < game <= settled
                or str(row.get("outcome_source") or "").lower() not in _FINAL_SOURCES
                or row.get("outcome") not in {"Win", "Loss"} or row.get("direction") not in {"Over", "Under"}):
            continue
        try:
            actual, line, probability = (float(row[field]) for field in ("actual", "line", "probability"))
        except (TypeError, ValueError, KeyError):
            continue
        if not all(isfinite(value) for value in (actual, line, probability)) or actual == line or not 0 <= probability <= 100:
            continue
        if row["outcome"] != ("Win" if (actual > line) == (row["direction"] == "Over") else "Loss"):
            continue
        independent[key] = (row, _categories(snapshot))

    def metrics(group: list[dict]) -> dict:
        count = len(group)
        wins = sum(row["outcome"] == "Win" for row in group)
        return {
            "samples": count,
            "wins": wins,
            "hit_rate": round(wins / count * 100, 1) if count else None,
            "brier": round(sum(((float(row["probability"]) / 100) - (row["outcome"] == "Win")) ** 2 for row in group) / count, 4) if count else None,
        }

    categories = []
    for category in _CATEGORIES:
        included = [row for row, present in independent.values() if category in present]
        excluded = [row for row, present in independent.values() if category not in present]
        categories.append({
            "key": category,
            "label": category.replace("_", " ").title(),
            "included": metrics(included),
            "not_included": metrics(excluded),
            "descriptive_only": True,
            "small_sample": min(len(included), len(excluded)) < 100,
        })
    return {
        "independent_outcomes": len(independent), "records_examined": len(rows), "truncated": truncated,
        "categories": categories, "ablation": {"available": False, "reason": "Historical feature-removal forecasts have not been recomputed and validated chronologically."},
        "note": "Descriptive associations only. Evidence presence is not a causal effect, paid-ready gate, or profitability claim. Only verified pregame forecasts and the first record per independent market are counted.",
    }


def evidence_lab(sport: str = "", provider: str = "", stat: str = "", model_version: str = "") -> dict:
    with SessionLocal() as session:
        query = session.query(*(getattr(PredictionRecordModel, field) for field in _FIELDS)).filter(
            PredictionRecordModel.legacy_quarantined.is_(False),
            PredictionRecordModel.outcome.in_(("Win", "Loss")),
        )
        for field, value in (("sport", sport.upper()), ("platform", provider), ("model_version", model_version)):
            if value:
                query = query.filter(getattr(PredictionRecordModel, field) == value)
        if stat:
            query = query.filter(PredictionRecordModel.stat.in_({stat, canonical_stat_label(stat)}))
        records = query.order_by(PredictionRecordModel.predicted_at.asc(), PredictionRecordModel.id.asc()).limit(5001).all()
    rows = [dict(zip(_FIELDS, record, strict=True)) for record in records[:5000]]
    return summarize_evidence_lab(rows, truncated=len(records) > 5000)
