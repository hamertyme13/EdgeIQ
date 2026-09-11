from __future__ import annotations

import json
import os

from repository.database import SessionLocal, initialize_database
from repository.models.background_job_model import BackgroundJobModel


class BackgroundJobRepository:
    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if not BackgroundJobRepository._schema_ready:
            initialize_database()
            BackgroundJobRepository._schema_ready = True

    @staticmethod
    def save(job: dict) -> None:
        BackgroundJobRepository._ensure_schema()
        with SessionLocal() as session:
            row = session.query(BackgroundJobModel).filter_by(job_id=job["job_id"]).first()
            if row is None:
                row = BackgroundJobModel(job_id=job["job_id"])
                session.add(row)
            row.kind = str(job.get("kind") or "job")
            row.label = str(job.get("label") or "")
            row.dedupe_key = str(job.get("dedupe_key") or "")
            row.status = str(job.get("status") or "queued")
            row.progress = int(job.get("progress") or 0)
            row.phase = str(job.get("phase") or "")
            row.created_at = str(job.get("created_at") or "")
            row.started_at = str(job.get("started_at") or "")
            row.completed_at = str(job.get("completed_at") or "")
            row.cancel_requested = bool(job.get("cancel_requested"))
            row.result_json = json.dumps(job.get("result") or {}, default=str, sort_keys=True)
            row.error = str(job.get("error") or "")
            row.owner_id = str(job.get("_owner_id") or "")
            row.process_id = int(job.get("_process_id") or 0)
            row.heartbeat_at = str(job.get("_heartbeat_at") or "")
            session.commit()

    @staticmethod
    def get(job_id: str) -> dict | None:
        BackgroundJobRepository._ensure_schema()
        with SessionLocal() as session:
            row = session.query(BackgroundJobModel).filter_by(job_id=job_id).first()
            return _serialize(row) if row else None

    @staticmethod
    def active(dedupe_key: str) -> dict | None:
        BackgroundJobRepository._ensure_schema()
        with SessionLocal() as session:
            rows = (
                session.query(BackgroundJobModel)
                .filter_by(dedupe_key=dedupe_key)
                .filter(BackgroundJobModel.status.in_(("queued", "running", "canceling")))
                .order_by(BackgroundJobModel.id.desc())
                .all()
            )
            return next((_serialize(row) for row in rows if _process_alive(row.process_id)), None)

    @staticmethod
    def recent(limit: int = 100) -> list[dict]:
        BackgroundJobRepository._ensure_schema()
        with SessionLocal() as session:
            rows = (
                session.query(BackgroundJobModel)
                .order_by(BackgroundJobModel.id.desc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            return [_serialize(row) for row in reversed(rows)]

    @staticmethod
    def recover_interrupted(completed_at: str) -> list[dict]:
        BackgroundJobRepository._ensure_schema()
        with SessionLocal() as session:
            rows = (
                session.query(BackgroundJobModel)
                .filter(BackgroundJobModel.status.in_(("queued", "running", "canceling")))
                .all()
            )
            recovered = []
            for row in rows:
                if _process_alive(row.process_id):
                    continue
                row.status = "failed"
                row.progress = 100
                row.phase = "The app restarted before this job finished. Run it again."
                row.completed_at = completed_at
                row.error = "This job was interrupted by an app restart."
                recovered.append(_serialize(row))
            session.commit()
            return recovered


def _serialize(row: BackgroundJobModel) -> dict:
    try:
        result = json.loads(row.result_json or "{}")
    except (TypeError, ValueError):
        result = {}
    return {
        "job_id": row.job_id,
        "kind": row.kind,
        "label": row.label,
        "dedupe_key": row.dedupe_key,
        "status": row.status,
        "progress": row.progress,
        "phase": row.phase,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "cancel_requested": bool(row.cancel_requested),
        "result": result if isinstance(result, dict) else {},
        "error": row.error,
        "_owner_id": row.owner_id,
        "_process_id": row.process_id,
        "_heartbeat_at": row.heartbeat_at,
    }


def _process_alive(process_id: int | None) -> bool:
    if not process_id or int(process_id) <= 0:
        return False
    try:
        os.kill(int(process_id), 0)
        return True
    except (OSError, ValueError):
        return False
