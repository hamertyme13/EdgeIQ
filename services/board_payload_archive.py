"""Bounded, reversible cold storage for old raw offer payloads."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from repository.database import DATABASE_URL
from services.data_management import _sqlite_path
from services.operation_lock import named_operation_lock


def archive_board_payload_batch(
    *,
    database_url: str | None = None,
    archive_dir: str | Path = ".edgeiq_archives",
    backup_path: str | Path | None = None,
    retention_days: int = 21,
    limit: int = 1000,
    execute: bool = False,
    now: datetime | None = None,
) -> dict:
    """Archive raw JSON only; keep every offer, line, model field, and outcome in SQLite."""
    if retention_days < 14 or not 1 <= limit <= 5000:
        raise ValueError("Retention must be at least 14 days and a batch must contain 1-5,000 rows.")
    source = _sqlite_path(database_url or DATABASE_URL)
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(source, timeout=30) as connection:
        rows = connection.execute(
            "SELECT id, captured_at, provider_payload FROM board_offer_observations "
            "WHERE captured_at < ? AND provider_payload <> '' "
            "ORDER BY captured_at, id LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    preview = {"cutoff": cutoff, "batch_rows": len(rows), "retention_days": retention_days,
               "limit": limit, "execute": execute, "archived_path": "", "cleared_payloads": 0}
    if not execute or not rows:
        return preview
    _verify_backup(source, backup_path)
    with named_operation_lock("database-maintenance") as acquired:
        if not acquired:
            raise ValueError("Another database backup or maintenance task is already running.")
        destination = Path(archive_dir)
        destination.mkdir(parents=True, exist_ok=True)
        name = f"board-payloads-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.jsonl.gz"
        archive = destination / name
        partial = destination / f".{name}.partial"
        digest = hashlib.sha256()
        try:
            with gzip.open(partial, "wt", encoding="utf-8") as output:
                for row_id, captured_at, payload in rows:
                    line = json.dumps({"id": row_id, "captured_at": captured_at, "provider_payload": payload}, separators=(",", ":")) + "\n"
                    output.write(line)
                    digest.update(line.encode("utf-8"))
            with partial.open("rb") as handle:
                os.fsync(handle.fileno())
            partial.replace(archive)
            with sqlite3.connect(source, timeout=30) as connection:
                connection.execute("BEGIN IMMEDIATE")
                updated = 0
                for row_id, _captured_at, payload in rows:
                    updated += connection.execute(
                        "UPDATE board_offer_observations SET provider_payload = '' "
                        "WHERE id = ? AND provider_payload = ? AND captured_at < ?",
                        (row_id, payload, cutoff),
                    ).rowcount
                if updated != len(rows):
                    connection.rollback()
                    raise RuntimeError("An offer changed during archival; no payloads were cleared.")
                connection.commit()
        finally:
            partial.unlink(missing_ok=True)
    return {**preview, "archived_path": str(archive.resolve()), "cleared_payloads": len(rows),
            "sha256_uncompressed": digest.hexdigest(),
            "note": "Offer rows and settled evidence remain in SQLite; only raw provider JSON moved to reversible cold storage."}


def restore_board_payload_batch(archive_path: str | Path, *, database_url: str | None = None) -> int:
    source = _sqlite_path(database_url or DATABASE_URL)
    restored = 0
    with named_operation_lock("database-maintenance") as acquired:
        if not acquired:
            raise ValueError("Another database backup or maintenance task is already running.")
        with gzip.open(archive_path, "rt", encoding="utf-8") as handle, sqlite3.connect(source, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for line in handle:
                record = json.loads(line)
                restored += connection.execute(
                    "UPDATE board_offer_observations SET provider_payload = ? "
                    "WHERE id = ? AND captured_at = ? AND provider_payload = ''",
                    (record["provider_payload"], record["id"], record["captured_at"]),
                ).rowcount
            connection.commit()
    return restored


def _verify_backup(source: Path, backup_path: str | Path | None) -> None:
    if backup_path is None:
        raise ValueError("A separate, completed SQLite backup is required before changing offer payloads.")
    backup = Path(backup_path)
    if not backup.is_file() or backup.resolve() == source.resolve():
        raise ValueError("Provide an existing backup file separate from the database being maintained.")
    with backup.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise ValueError("The backup is not a SQLite database.")
