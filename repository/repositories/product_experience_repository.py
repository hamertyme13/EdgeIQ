from __future__ import annotations

import hashlib
import json

from sqlalchemy import func

from repository.database import SessionLocal, initialize_database
from repository.models.product_event_model import ProductEventModel
from repository.models.research_session_model import ResearchSessionModel
from utils.time import utc_now


class ProductExperienceRepository:
    FUNNEL = ("recommendation_viewed", "entry_analyzed", "recommendation_added", "entry_saved", "entry_settled")

    @staticmethod
    def record_event(
        event_name: str,
        entity_type: str = "",
        entity_id: str = "",
        metadata: dict | None = None,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> dict:
        initialize_database()
        with SessionLocal() as session:
            if event_name == "entry_settled" and user_id is None and entity_id:
                saved = session.query(ProductEventModel).filter_by(
                    event_name="entry_saved",
                    entity_type="entry",
                    entity_id=entity_id,
                ).order_by(ProductEventModel.created_at.desc()).first()
                if saved is not None:
                    user_id = saved.user_id
                    session_id = saved.session_id
            row = ProductEventModel(
                user_id=user_id,
                session_id=session_id,
                event_name=event_name,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata_json=json.dumps(metadata or {}, default=str, sort_keys=True),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return {"id": row.id, "event": row.event_name, "created_at": row.created_at.isoformat()}

    @staticmethod
    def analytics() -> dict:
        initialize_database()
        with SessionLocal() as session:
            counts = dict(session.query(ProductEventModel.event_name, func.count(ProductEventModel.id)).group_by(ProductEventModel.event_name).all())
        viewed = int(counts.get("recommendation_viewed", 0))
        return {"funnel": [{"event": event, "count": int(counts.get(event, 0))} for event in ProductExperienceRepository.FUNNEL], "conversion": {"view_to_analyze": _rate(counts.get("entry_analyzed", 0), viewed), "view_to_save": _rate(counts.get("entry_saved", 0), viewed), "save_to_settle": _rate(counts.get("entry_settled", 0), counts.get("entry_saved", 0))}}

    @staticmethod
    def event_counts(*, user_id: int | None = None) -> dict[str, int]:
        initialize_database()
        with SessionLocal() as session:
            query = session.query(ProductEventModel.event_name, func.count(ProductEventModel.id))
            if user_id is not None:
                query = query.filter(ProductEventModel.user_id == int(user_id))
            return {name: int(count) for name, count in query.group_by(ProductEventModel.event_name).all()}

    @staticmethod
    def save_research(payload: dict) -> dict:
        initialize_database()
        identity = {key: payload.get(key) for key in ("player", "sport", "stat", "platform", "line")}
        fingerprint = hashlib.sha256(json.dumps(identity, default=str, sort_keys=True).lower().encode()).hexdigest()
        now = utc_now().replace(tzinfo=None)
        with SessionLocal() as session:
            row = session.query(ResearchSessionModel).filter_by(fingerprint=fingerprint).one_or_none()
            if row is None:
                row = ResearchSessionModel(fingerprint=fingerprint, **identity)
                session.add(row)
            else:
                row.run_count += 1
            row.summary_json = json.dumps(payload.get("summary") or {}, default=str, sort_keys=True)
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return _research_row(row)

    @staticmethod
    def recent_research(limit: int = 12) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(ResearchSessionModel).order_by(ResearchSessionModel.updated_at.desc()).limit(max(1, min(limit, 50))).all()
            return [_research_row(row) for row in rows]


def _rate(numerator: int, denominator: int) -> float:
    return round((float(numerator) / float(denominator)) * 100.0, 1) if denominator else 0.0


def _research_row(row: ResearchSessionModel) -> dict:
    try:
        summary = json.loads(row.summary_json or "{}")
    except json.JSONDecodeError:
        summary = {}
    return {"id": row.id, "player": row.player, "sport": row.sport, "stat": row.stat, "platform": row.platform, "line": row.line, "summary": summary, "run_count": row.run_count, "updated_at": row.updated_at.isoformat() if row.updated_at else ""}
