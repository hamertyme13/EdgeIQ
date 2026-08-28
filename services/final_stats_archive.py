from __future__ import annotations

import gzip
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, func

from repository.database import SessionLocal
from repository.models.final_player_stat_model import FinalPlayerStatModel
from utils.time import utc_now


def archive_final_stats(*, retention_days: int = 730, dry_run: bool = True) -> dict:
    """Export old final-stat evidence before optionally removing active copies."""
    days = max(365, int(retention_days))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with SessionLocal() as session:
        count = int(
            session.query(func.count(FinalPlayerStatModel.id))
            .filter(FinalPlayerStatModel.game_date < cutoff)
            .scalar()
            or 0
        )
    if dry_run or not count:
        return {
            "dry_run": dry_run,
            "eligible_rows": count,
            "retention_days": days,
            "cutoff": cutoff,
            "archive_path": "",
            "deleted_rows": 0,
        }

    archive_dir = Path(".edgeiq_archives")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"final-stats-before-{cutoff}-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.jsonl.gz"
    exported = 0
    with SessionLocal() as session, gzip.open(archive_path, "wt", encoding="utf-8") as handle:
        query = (
            session.query(FinalPlayerStatModel)
            .filter(FinalPlayerStatModel.game_date < cutoff)
            .order_by(FinalPlayerStatModel.id.asc())
            .yield_per(1000)
        )
        for row in query:
            handle.write(json.dumps({
                "id": row.id,
                "player": row.player,
                "team": row.team,
                "sport": row.sport,
                "stat": row.stat,
                "game": row.game,
                "game_date": row.game_date,
                "actual": row.actual,
                "status": row.status,
                "source": row.source,
                "player_identity_id": row.player_identity_id,
                "player_provider": row.player_provider,
                "provider_player_id": row.provider_player_id,
            }, sort_keys=True) + "\n")
            exported += 1
        session.execute(delete(FinalPlayerStatModel).where(FinalPlayerStatModel.game_date < cutoff))
        session.commit()
    return {
        "dry_run": False,
        "eligible_rows": count,
        "exported_rows": exported,
        "deleted_rows": exported,
        "retention_days": days,
        "cutoff": cutoff,
        "archive_path": str(archive_path.resolve()),
    }
