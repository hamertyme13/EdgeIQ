from __future__ import annotations

import hashlib
import json

from sqlalchemy.exc import IntegrityError

from repository.database import SessionLocal, initialize_database
from repository.models.plausibility_rejection_model import PlausibilityRejectionModel
from utils.prop_plausibility import PlausibilityResult
from utils.time import utc_now


class PlausibilityRejectionRepository:
    @staticmethod
    def record(payload: dict, result: PlausibilityResult, *, provider: str = "") -> dict:
        """Persist a rejected provider row without changing its original representation."""
        return PlausibilityRejectionRepository.record_many([(payload, result, provider)])[0]

    @staticmethod
    def record_many(items: list[tuple[dict, PlausibilityResult, str]]) -> list[dict]:
        """Batch provider diagnostics so a large rejected board uses one transaction."""
        if not items:
            return []
        initialize_database()
        now = utc_now().replace(tzinfo=None)
        prepared: dict[str, dict] = {}
        order: list[str] = []
        for payload, result, provider in items:
            source = str(provider or payload.get("platform") or payload.get("provider") or "unknown")
            fingerprint = _fingerprint(source, payload, result)
            if fingerprint not in prepared:
                prepared[fingerprint] = {
                    "payload": payload,
                    "result": result,
                    "provider": source,
                    "count": 0,
                }
            prepared[fingerprint]["count"] += 1
            order.append(fingerprint)

        with SessionLocal() as session:
            existing = {
                row.fingerprint: row
                for row in session.query(PlausibilityRejectionModel)
                .filter(PlausibilityRejectionModel.fingerprint.in_(list(prepared)))
                .all()
            }
            for fingerprint, item in prepared.items():
                row = existing.get(fingerprint)
                if row is not None:
                    _increment_occurrence(session, fingerprint, now, item["count"])
                    continue
                result = item["result"]
                row = PlausibilityRejectionModel(
                    fingerprint=fingerprint,
                    rejection_reason=result.reason,
                    original_provider_payload=json.dumps(item["payload"], default=str, sort_keys=True),
                    provider=item["provider"],
                    rejected_at=now,
                    last_seen_at=now,
                    normalized_value="" if result.line is None else str(result.line),
                    expected_minimum=result.minimum,
                    expected_maximum=result.maximum,
                    sport=result.sport,
                    stat=result.stat,
                    occurrence_count=item["count"],
                )
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    _increment_occurrence(session, fingerprint, now, item["count"])
            session.commit()
            stored = {
                row.fingerprint: _serialize(row)
                for row in session.query(PlausibilityRejectionModel)
                .filter(PlausibilityRejectionModel.fingerprint.in_(list(prepared)))
                .all()
            }
            return [stored[fingerprint] for fingerprint in order]

    @staticmethod
    def recent(*, limit: int = 100) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            rows = (
                session.query(PlausibilityRejectionModel)
                .order_by(PlausibilityRejectionModel.last_seen_at.desc(), PlausibilityRejectionModel.id.desc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            return [_serialize(row) for row in rows]


def _fingerprint(provider: str, payload: dict, result: PlausibilityResult) -> str:
    identity = {
        "provider": provider,
        "player": payload.get("player"),
        "sport": result.sport,
        "stat": result.stat,
        "line": result.line,
        "game": payload.get("game"),
        "provider_offer_id": payload.get("provider_offer_id") or payload.get("projection_id") or payload.get("id"),
        "reason": result.reason,
    }
    return hashlib.sha256(json.dumps(identity, default=str, sort_keys=True).encode()).hexdigest()


def _increment_occurrence(session, fingerprint: str, now, count: int = 1) -> None:
    session.query(PlausibilityRejectionModel).filter_by(fingerprint=fingerprint).update(
        {
            PlausibilityRejectionModel.last_seen_at: now,
            PlausibilityRejectionModel.occurrence_count: PlausibilityRejectionModel.occurrence_count + count,
        },
        synchronize_session=False,
    )


def _serialize(row: PlausibilityRejectionModel) -> dict:
    return {
        "id": row.id,
        "rejection_reason": row.rejection_reason,
        "original_provider_payload": json.loads(row.original_provider_payload),
        "provider": row.provider,
        "timestamp": row.rejected_at.isoformat() if row.rejected_at else "",
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else "",
        "normalized_value": row.normalized_value,
        "expected_range": {"minimum": row.expected_minimum, "maximum": row.expected_maximum},
        "sport": row.sport,
        "stat": row.stat,
        "occurrence_count": row.occurrence_count,
    }
