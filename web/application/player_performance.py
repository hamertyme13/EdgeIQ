"""Read-only player presentation over the existing prediction ledger."""
from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite

from sqlalchemy import or_

from analytics.model_version_evaluation import evaluate_model_versions
from repository.database import SessionLocal
from repository.models.player_identity_model import PlayerIdentityModel
from repository.models.prediction_record_model import PredictionRecordModel
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label


def _time(value: object) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
    except (TypeError, ValueError):
        return None


def performance_summary(rows: list[dict]) -> dict:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        predicted, game, settled = (_time(row.get(key)) for key in ("predicted_at", "game_time", "settled_at"))
        feature_time = _time(row.get("feature_as_of"))
        version = str(row.get("model_version") or "")
        if (row.get("legacy_quarantined") or not row.get("player_identity_id")
                or not row.get("independent_market_key") or not version or "legacy" in version.lower()
                or row.get("result") not in {"Win", "Loss"}
                or row.get("outcome_source") not in {"espn", "mlb_statsapi", "nba_api", "pandascore"}
                or not predicted or not game or not settled or not feature_time
                or not feature_time <= predicted < game <= settled):
            continue
        try:
            probability, actual, line = (float(row[key]) for key in ("probability", "actual", "line"))
        except (ValueError, TypeError, KeyError):
            continue
        if not all(isfinite(value) for value in (probability, actual, line)) or not 0 <= probability <= 100:
            continue
        direction = row.get("direction")
        if direction not in {"Over", "Under"} or actual == line:
            continue
        expected = "Win" if ((actual > line) == (direction == "Over")) else "Loss"
        if expected != row["result"]:
            continue
        grouped[(version, str(row.get("platform") or ""), direction)].append(row)
    versions = []
    for (_version, platform, direction), records in sorted(grouped.items()):
        records.sort(key=lambda row: _time(row["predicted_at"]) or datetime.min.replace(tzinfo=UTC))
        # Preserve the first locked forecast per market, not the most favorable duplicate.
        independent: dict[str, dict] = {}
        for row in records:
            independent.setdefault(row["independent_market_key"], row)
        metrics = evaluate_model_versions(list(independent.values()))["versions"]
        if metrics:
            result = {key: value for key, value in metrics[0].items() if key != "promotion_eligible"}
            result["wins"] = sum(row["result"] == "Win" for row in independent.values())
            result["losses"] = sum(row["result"] == "Loss" for row in independent.values())
            versions.append({**result, "platform": platform, "direction": direction,
                             "small_sample": result["settled_predictions"] < 100})
    return {"versions": versions, "roi": None, "score_buckets": None,
            "note": "Player-specific independent pregame predictions only. ROI and stored-score performance are not verified here."}


def player_performance(player: str, sport: str, stat: str, platform: str) -> dict:
    if not sport or sport == "All Sports":
        return performance_summary([])
    with SessionLocal() as session:
        identities = session.query(PlayerIdentityModel.id).filter(
            PlayerIdentityModel.canonical_key == canonical_person_key(player), PlayerIdentityModel.sport == sport.upper())
        query = session.query(PredictionRecordModel).filter(
            PredictionRecordModel.sport == sport.upper(),
            PredictionRecordModel.stat.in_([stat, canonical_stat_label(stat)]),
            PredictionRecordModel.legacy_quarantined.is_(False),
            or_(PredictionRecordModel.player == player, PredictionRecordModel.player_identity_id.in_(identities)),
        )
        if platform not in {"Both", "All", "All Platforms"}:
            query = query.filter(PredictionRecordModel.platform == platform)
        rows = query.order_by(PredictionRecordModel.predicted_at.desc(), PredictionRecordModel.id.desc()).limit(1000).all()
        fields = ("player_identity_id", "independent_market_key", "model_version", "legacy_quarantined",
                  "outcome_source", "predicted_at", "game_time", "settled_at", "feature_as_of",
                  "probability", "actual", "line", "direction", "platform")
        payload = [{**{key: getattr(row, key) for key in fields}, "result": row.outcome}
                   for row in rows if canonical_stat_label(row.stat) == canonical_stat_label(stat)]
    return {**performance_summary(payload), "records_examined": len(rows), "window_limit": 1000}
