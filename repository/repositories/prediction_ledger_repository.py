from __future__ import annotations

import json

from analytics.edgeiq_model import MODEL_VERSION as LEGACY_MODEL_VERSION
from analytics.prediction_evidence import independent_market_key, offer_key
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
        return {
            "records": len(rows),
            "versioned_records": sum(1 for row in rows if not row["legacy_quarantined"]),
            "legacy_quarantined": sum(1 for row in rows if row["legacy_quarantined"]),
            "settled_unique_markets": len(unique),
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
