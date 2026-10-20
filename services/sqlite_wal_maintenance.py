from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from services.operation_lock import named_operation_lock

MIN_CHECKPOINT_BYTES = 32 * 1024 * 1024


def checkpoint_large_wal(engine: Engine, *, minimum_bytes: int = MIN_CHECKPOINT_BYTES) -> bool:
    """Backfill a large SQLite WAL while the app is idle, before final connection close."""
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        return False
    wal_path = Path(f"{engine.url.database}-wal")
    if not wal_path.exists() or wal_path.stat().st_size < minimum_bytes:
        return False
    with named_operation_lock("sqlite-wal-checkpoint") as acquired:
        if not acquired:
            return False
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            busy, frames, checkpointed = connection.exec_driver_sql("PRAGMA wal_checkpoint(PASSIVE)").one()
        return busy == 0 and frames == checkpointed
