from __future__ import annotations

import base64
import json
import shutil
import sqlite3
from datetime import UTC, date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from repository.database import DATABASE_URL
from services.operation_lock import named_operation_lock

EXPORT_SCHEMA_VERSION = 1


def backup_database(
    destination_dir: str | Path = ".edgeiq_backups",
    *,
    database_url: str | None = None,
) -> dict:
    with named_operation_lock("database-maintenance") as acquired:
        if not acquired:
            raise ValueError("Another database backup or maintenance task is already running.")
        return _backup_database_unlocked(destination_dir, database_url=database_url)


def _backup_database_unlocked(
    destination_dir: str | Path,
    *,
    database_url: str | None = None,
) -> dict:
    source_path = _sqlite_path(database_url or DATABASE_URL)
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _require_backup_space(source_path, destination)
    created_at = datetime.now(UTC)
    backup_path = destination / f"edgeiq-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}.db"

    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)

    return {
        "created_at": created_at.isoformat(),
        "path": str(backup_path.resolve()),
        "bytes": backup_path.stat().st_size,
        "format": "sqlite",
    }


def export_database(
    destination_dir: str | Path = ".edgeiq_exports",
    *,
    database_url: str | None = None,
) -> dict:
    with named_operation_lock("database-maintenance") as acquired:
        if not acquired:
            raise ValueError("Another database backup or maintenance task is already running.")
        return _export_database_unlocked(destination_dir, database_url=database_url)


def _export_database_unlocked(
    destination_dir: str | Path,
    *,
    database_url: str | None = None,
) -> dict:
    source_path = _sqlite_path(database_url or DATABASE_URL)
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _require_export_space(source_path, destination)
    created_at = datetime.now(UTC)
    suffix = created_at.strftime("%Y%m%dT%H%M%S%fZ")
    export_path = destination / f"edgeiq-export-{suffix}.json"
    partial_path = destination / f".edgeiq-export-{suffix}.partial"
    table_counts: dict[str, int] = {}

    try:
        with sqlite3.connect(source_path) as connection, partial_path.open("w", encoding="utf-8") as output:
            connection.row_factory = sqlite3.Row
            table_rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            output.write(
                '{"schema_version":'
                + str(EXPORT_SCHEMA_VERSION)
                + ',"created_at":'
                + json.dumps(created_at.isoformat())
                + ',"source":"EdgeIQ","tables":{'
            )
            for table_index, table_row in enumerate(table_rows):
                table_name = str(table_row["name"])
                if table_index:
                    output.write(",")
                output.write(json.dumps(table_name, ensure_ascii=True) + ":[")
                cursor = connection.execute(f"SELECT * FROM {_quote_identifier(table_name)}")
                count = 0
                first_record = True
                while records := cursor.fetchmany(500):
                    for record in records:
                        if not first_record:
                            output.write(",")
                        payload = {key: _json_value(value) for key, value in dict(record).items()}
                        output.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
                        first_record = False
                        count += 1
                output.write("]")
                table_counts[table_name] = count
            output.write("}}")
        partial_path.replace(export_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return {
        "created_at": created_at.isoformat(),
        "path": str(export_path.resolve()),
        "bytes": export_path.stat().st_size,
        "format": "json",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "tables": table_counts,
    }


def compact_board_history(
    *,
    execute: bool = False,
    database_url: str | None = None,
    backup_destination: str | Path = ".edgeiq_backups",
) -> dict:
    """Preview or remove redundant intra-hour provider-board checkpoints."""
    resolved_url = database_url or DATABASE_URL
    source_path = _sqlite_path(resolved_url)
    with sqlite3.connect(source_path, timeout=30) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_offer_observations'"
        ).fetchone()
        if not table_exists:
            return {
                "execute": execute,
                "before": 0,
                "after": 0,
                "eligible": 0,
                "removed": 0,
                "backup": None,
                "message": "No provider-board history exists yet.",
            }
        before = int(connection.execute("SELECT COUNT(*) FROM board_offer_observations").fetchone()[0])
        eligible = int(connection.execute(f"SELECT COUNT(*) FROM ({_redundant_board_rows_sql()})").fetchone()[0])

    if not execute or not eligible:
        return {
            "execute": execute,
            "before": before,
            "after": before,
            "eligible": eligible,
            "removed": 0,
            "backup": None,
            "message": (
                f"{eligible:,} redundant hourly checkpoints can be removed after confirmation."
                if eligible
                else "Provider-board history is already optimized."
            ),
        }

    with named_operation_lock("database-maintenance") as acquired:
        if not acquired:
            raise ValueError("Another database backup or maintenance task is already running.")
        backup = _backup_database_unlocked(backup_destination, database_url=resolved_url)
        removed = 0
        with sqlite3.connect(source_path, timeout=30) as connection:
            connection.execute(
                "CREATE TEMP TABLE edgeiq_compaction_ids (id INTEGER PRIMARY KEY)"
            )
            connection.execute(
                f"INSERT INTO edgeiq_compaction_ids (id) {_redundant_board_rows_sql()}"
            )
            while True:
                ids = [
                    int(row[0])
                    for row in connection.execute(
                        "SELECT id FROM edgeiq_compaction_ids LIMIT 5000"
                    ).fetchall()
                ]
                if not ids:
                    break
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM board_offer_observations WHERE id IN ({placeholders})",
                    ids,
                )
                connection.execute(
                    f"DELETE FROM edgeiq_compaction_ids WHERE id IN ({placeholders})",
                    ids,
                )
                connection.commit()
                removed += len(ids)
            connection.execute("PRAGMA optimize")
            after = int(connection.execute("SELECT COUNT(*) FROM board_offer_observations").fetchone()[0])
    return {
        "execute": True,
        "before": before,
        "after": after,
        "eligible": eligible,
        "removed": removed,
        "backup": backup,
        "message": f"Removed {removed:,} redundant checkpoints. Opening, latest, changed, analyzed, and settled evidence was preserved.",
    }


def _redundant_board_rows_sql() -> str:
    return """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY offer_key, strftime('%Y-%m-%dT%H:00:00', captured_at)
                    ORDER BY captured_at ASC, id ASC
                ) AS hourly_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY market_key
                    ORDER BY captured_at DESC, id DESC
                ) AS latest_market_rank,
                analyzed_at,
                settled_at,
                outcome,
                projection
            FROM board_offer_observations
        )
        SELECT id
        FROM ranked
        WHERE hourly_rank > 1
          AND latest_market_rank > 1
          AND analyzed_at IS NULL
          AND settled_at IS NULL
          AND COALESCE(outcome, '') = ''
          AND projection IS NULL
    """


def _sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Backup and export currently require a file-based SQLite database.")
    path = Path(url.database)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise FileNotFoundError(f"EdgeIQ database was not found at {path}.")
    return path


def _require_backup_space(source_path: Path, destination: Path) -> None:
    source_bytes = source_path.stat().st_size
    reserve_bytes = max(256 * 1024 * 1024, int(source_bytes * 0.05))
    required_bytes = source_bytes + reserve_bytes
    free_bytes = shutil.disk_usage(destination).free
    if free_bytes < required_bytes:
        required_gb = required_bytes / (1024 ** 3)
        free_gb = free_bytes / (1024 ** 3)
        raise OSError(
            f"Database backup needs about {required_gb:.1f} GB free, but only {free_gb:.1f} GB is available. "
            "Free storage or choose another backup destination before continuing."
        )


def _require_export_space(source_path: Path, destination: Path) -> None:
    source_bytes = source_path.stat().st_size
    reserve_bytes = max(256 * 1024 * 1024, int(source_bytes * 0.05))
    required_bytes = int(source_bytes * 1.5) + reserve_bytes
    free_bytes = shutil.disk_usage(destination).free
    if free_bytes < required_bytes:
        required_gb = required_bytes / (1024 ** 3)
        free_gb = free_bytes / (1024 ** 3)
        raise OSError(
            f"Database export needs about {required_gb:.1f} GB free, but only {free_gb:.1f} GB is available. "
            "Free storage or choose another export destination before continuing."
        )


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'
