from __future__ import annotations

import json

from repository.database import SessionLocal, initialize_database
from repository.models.settlement_audit_model import SettlementAuditModel
from utils.time import utc_now


class SettlementAuditRepository:
    @staticmethod
    def record(payload: dict) -> None:
        initialize_database()
        entry_prop_id = int(payload.get("entry_prop_id") or 0)
        if not entry_prop_id:
            return
        status = str(payload.get("status") or "pending")
        provider = str(payload.get("provider") or "")
        reason_code = str(payload.get("reason_code") or "")
        with SessionLocal() as session:
            row = (
                session.query(SettlementAuditModel)
                .filter_by(
                    entry_prop_id=entry_prop_id,
                    status=status,
                    provider=provider,
                    reason_code=reason_code,
                )
                .first()
            )
            values = {
                "entry_id": int(payload.get("entry_id") or 0),
                "entry_prop_id": entry_prop_id,
                "status": status,
                "provider": provider,
                "matched_identity_id": payload.get("matched_identity_id"),
                "requested_player": str(payload.get("requested_player") or ""),
                "matched_player": str(payload.get("matched_player") or ""),
                "requested_game": str(payload.get("requested_game") or ""),
                "matched_game": str(payload.get("matched_game") or ""),
                "actual": payload.get("actual"),
                "result": str(payload.get("result") or ""),
                "reason_code": reason_code,
                "message": str(payload.get("message") or ""),
                "details": json.dumps(payload.get("details") or {}),
                "attempted_at": utc_now(),
            }
            if row is None:
                session.add(SettlementAuditModel(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.attempt_count = int(row.attempt_count or 0) + 1
            session.commit()

    @staticmethod
    def queue(limit: int = 100) -> dict:
        initialize_database()
        with SessionLocal() as session:
            rows = (
                session.query(SettlementAuditModel)
                .order_by(SettlementAuditModel.attempted_at.desc(), SettlementAuditModel.id.desc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            latest: dict[int, SettlementAuditModel] = {}
            for row in rows:
                latest.setdefault(row.entry_prop_id, row)
            items = [_serialize(row) for row in latest.values()]
        counts: dict[str, int] = {}
        for item in items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {
            "items": items,
            "count": len(items),
            "verified": counts.get("verified", 0),
            "waiting": counts.get("waiting", 0),
            "blocked": counts.get("blocked", 0),
            "statuses": counts,
        }


def _serialize(row: SettlementAuditModel) -> dict:
    try:
        details = json.loads(row.details or "{}")
    except (TypeError, ValueError):
        details = {}
    return {
        "id": row.id,
        "entry_id": row.entry_id,
        "entry_prop_id": row.entry_prop_id,
        "status": row.status,
        "provider": row.provider,
        "matched_identity_id": row.matched_identity_id,
        "requested_player": row.requested_player,
        "matched_player": row.matched_player,
        "requested_game": row.requested_game,
        "matched_game": row.matched_game,
        "actual": row.actual,
        "result": row.result,
        "reason_code": row.reason_code,
        "message": row.message,
        "attempt_count": row.attempt_count,
        "attempted_at": row.attempted_at.isoformat() if row.attempted_at else "",
        "details": details,
    }
