from __future__ import annotations

import json

from analytics.edgeiq_model import MODEL_VERSION as LEGACY_MODEL_VERSION
from analytics.prediction_evidence import deduplicate_outcomes, independent_market_key, offer_key
from repository.database import SessionLocal, initialize_database
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.prediction_record_model import PredictionRecordModel
from utils.time import utc_now


class PredictionLedgerRepository:
    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if PredictionLedgerRepository._schema_ready:
            return
        initialize_database()
        PredictionLedgerRepository._schema_ready = True

    @staticmethod
    def record(session, entry: EntryModel, prop: EntryPropModel, domain_prop, payout_snapshot: str) -> None:
        payload = _prop_payload(prop)
        existing = session.query(PredictionRecordModel).filter_by(entry_prop_id=prop.id).first()
        if existing is not None:
            return
        snapshot = getattr(domain_prop, "forecast_snapshot", None) or {}
        session.add(PredictionRecordModel(
            entry_id=entry.id,
            entry_prop_id=prop.id,
            independent_market_key=independent_market_key(payload),
            offer_key=offer_key(payload),
            player_identity_id=prop.player_identity_id,
            player=prop.player_name,
            team=prop.team or "",
            sport=prop.sport,
            stat=prop.stat,
            direction=prop.direction or "Over",
            platform=prop.platform,
            game=prop.game or "",
            game_time=prop.game_time or "",
            line=float(prop.line or 0.0),
            projection=float(prop.projection or prop.line or 0.0),
            probability=float(prop.confidence or 50.0),
            projection_source=prop.projection_source or "",
            model_version=getattr(domain_prop, "model_version", "") or LEGACY_MODEL_VERSION,
            line_offer_type=prop.line_offer_type or "standard",
            feature_as_of=str(getattr(domain_prop, "feature_as_of", "") or ""),
            feature_snapshot=json.dumps(snapshot, sort_keys=True),
            payout_snapshot=payout_snapshot or "",
            legacy_quarantined=False,
        ))

    @staticmethod
    def settle(session, prop: EntryPropModel) -> None:
        record = session.query(PredictionRecordModel).filter_by(entry_prop_id=prop.id).first()
        if record is None:
            return
        record.outcome = prop.final_result or ""
        record.actual = prop.actual
        record.outcome_source = prop.final_source or ""
        record.settled_at = utc_now() if record.outcome else None

    @staticmethod
    def backfill_legacy_quarantine() -> int:
        PredictionLedgerRepository._ensure_schema()
        created = 0
        with SessionLocal() as session:
            existing_ids = {
                row[0] for row in session.query(PredictionRecordModel.entry_prop_id).all()
            }
            rows = (
                session.query(EntryPropModel, EntryModel)
                .join(EntryModel, EntryModel.id == EntryPropModel.entry_id)
                .all()
            )
            for prop, entry in rows:
                if prop.id in existing_ids:
                    continue
                payload = _prop_payload(prop)
                session.add(PredictionRecordModel(
                    entry_id=entry.id,
                    entry_prop_id=prop.id,
                    independent_market_key=independent_market_key(payload),
                    offer_key=offer_key(payload),
                    player_identity_id=prop.player_identity_id,
                    player=prop.player_name,
                    team=prop.team or "",
                    sport=prop.sport,
                    stat=prop.stat,
                    direction=prop.direction or "Over",
                    platform=prop.platform,
                    game=prop.game or "",
                    game_time=prop.game_time or "",
                    line=float(prop.line or 0.0),
                    projection=float(prop.projection or prop.line or 0.0),
                    probability=float(prop.confidence or 50.0),
                    projection_source=prop.projection_source or "legacy_unknown",
                    model_version="legacy-unversioned",
                    line_offer_type=prop.line_offer_type or "standard",
                    feature_as_of="",
                    feature_snapshot="",
                    payout_snapshot=entry.payout_table_snapshot or "",
                    legacy_quarantined=True,
                    outcome=prop.final_result or "",
                    actual=prop.actual,
                    outcome_source=prop.final_source or "",
                    predicted_at=entry.placed_at or entry.created_at or utc_now(),
                    settled_at=entry.settled_at if prop.final_result else None,
                ))
                created += 1
            session.commit()
        return created

    @staticmethod
    def quarantine_entry_props(entry_prop_ids: list[int]) -> int:
        PredictionLedgerRepository._ensure_schema()
        ids = {int(value) for value in entry_prop_ids if int(value) > 0}
        if not ids:
            return 0
        with SessionLocal() as session:
            rows = (
                session.query(PredictionRecordModel)
                .filter(PredictionRecordModel.entry_prop_id.in_(ids))
                .filter(PredictionRecordModel.legacy_quarantined.is_(False))
                .all()
            )
            for row in rows:
                row.legacy_quarantined = True
            session.commit()
            return len(rows)

    @staticmethod
    def evidence_rows(include_legacy: bool = False) -> list[dict]:
        PredictionLedgerRepository._ensure_schema()
        with SessionLocal() as session:
            query = session.query(PredictionRecordModel)
            if not include_legacy:
                query = query.filter(PredictionRecordModel.legacy_quarantined.is_(False))
            rows = query.order_by(PredictionRecordModel.predicted_at.asc()).all()
            return [
                {
                    "id": row.id,
                    "entry_id": row.entry_id,
                    "entry_prop_id": row.entry_prop_id,
                    "independent_market_key": row.independent_market_key,
                    "offer_key": row.offer_key,
                    "player_identity_id": row.player_identity_id,
                    "player": row.player,
                    "team": row.team,
                    "sport": row.sport,
                    "stat": row.stat,
                    "direction": row.direction,
                    "platform": row.platform,
                    "game": row.game,
                    "game_time": row.game_time,
                    "line": row.line,
                    "projection": row.projection,
                    "probability": row.probability,
                    "projection_source": row.projection_source,
                    "model_version": row.model_version,
                    "line_offer_type": row.line_offer_type,
                    "feature_snapshot": _json_dict(row.feature_snapshot),
                    "legacy_quarantined": bool(row.legacy_quarantined),
                    "result": row.outcome,
                    "actual": row.actual,
                    "outcome_source": row.outcome_source,
                    "predicted_at": row.predicted_at,
                    "settled_at": row.settled_at,
                }
                for row in rows
            ]

    @staticmethod
    def summary() -> dict:
        rows = PredictionLedgerRepository.evidence_rows(include_legacy=True)
        unique = {row["independent_market_key"] for row in rows if row["result"] in {"Win", "Loss", "Push"}}
        accuracy = _projection_accuracy(rows)
        return {
            "records": len(rows),
            "versioned_records": sum(1 for row in rows if not row["legacy_quarantined"]),
            "legacy_quarantined": sum(1 for row in rows if row["legacy_quarantined"]),
            "settled_unique_markets": len(unique),
            "projection_accuracy": accuracy,
        }


def _prop_payload(prop: EntryPropModel) -> dict:
    return {
        "player": prop.player_name,
        "player_identity_id": prop.player_identity_id,
        "team": prop.team,
        "sport": prop.sport,
        "stat": prop.stat,
        "line": prop.line,
        "direction": prop.direction,
        "platform": prop.platform,
        "game": prop.game,
        "game_time": prop.game_time,
        "line_offer_type": prop.line_offer_type,
    }


def _projection_accuracy(rows: list[dict]) -> dict:
    eligible = deduplicate_outcomes([
        row
        for row in rows
        if not row.get("legacy_quarantined")
        and row.get("actual") is not None
        and str(row.get("outcome_source") or "").strip().lower()
        not in {"", "unknown", "unmatched", "projection_estimate"}
    ])
    groups: dict[str, list[tuple[float, float]]] = {}
    errors = []
    market_errors = []
    regularized_errors = []
    signed = []
    distribution_predictions = 0
    middle_50_hits = 0
    floor_ceiling_hits = 0
    for row in eligible:
        error = float(row["projection"]) - float(row["actual"])
        errors.append(abs(error))
        market_error = abs(float(row["line"]) - float(row["actual"]))
        regularized_error = abs(
            ((float(row["projection"]) + float(row["line"])) / 2.0)
            - float(row["actual"])
        )
        market_errors.append(market_error)
        regularized_errors.append(regularized_error)
        signed.append(error)
        distribution = (row.get("feature_snapshot") or {}).get("distribution") or {}
        percentile_25 = distribution.get("percentile_25")
        percentile_75 = distribution.get("percentile_75")
        floor = distribution.get("floor")
        ceiling = distribution.get("ceiling")
        if all(value is not None for value in (percentile_25, percentile_75, floor, ceiling)):
            distribution_predictions += 1
            actual = float(row["actual"])
            middle_50_hits += int(float(str(percentile_25)) <= actual <= float(str(percentile_75)))
            floor_ceiling_hits += int(float(str(floor)) <= actual <= float(str(ceiling)))
        groups.setdefault(str(row.get("projection_source") or "unknown"), []).append(
            (abs(error), market_error)
        )
    projection_mae = sum(errors) / len(errors) if errors else None
    market_mae = sum(market_errors) / len(market_errors) if market_errors else None
    regularized_mae = (
        sum(regularized_errors) / len(regularized_errors)
        if regularized_errors
        else None
    )
    return {
        "verified_predictions": len(eligible),
        "mae": round(projection_mae, 3) if projection_mae is not None else None,
        "market_line_mae": round(market_mae, 3) if market_mae is not None else None,
        "regularized_mae": round(regularized_mae, 3) if regularized_mae is not None else None,
        "regularization_improvement_pct": (
            round((projection_mae - regularized_mae) / projection_mae * 100.0, 1)
            if projection_mae and regularized_mae is not None
            else None
        ),
        "bias": round(sum(signed) / len(signed), 3) if signed else None,
        "distribution_predictions": distribution_predictions,
        "middle_50_coverage": round(middle_50_hits / distribution_predictions * 100.0, 1) if distribution_predictions else None,
        "floor_ceiling_coverage": round(floor_ceiling_hits / distribution_predictions * 100.0, 1) if distribution_predictions else None,
        "by_source": {
            source: {
                "predictions": len(values),
                "mae": round(sum(value[0] for value in values) / len(values), 3),
                "market_line_mae": round(sum(value[1] for value in values) / len(values), 3),
            }
            for source, values in sorted(groups.items())
        },
    }


def _json_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
