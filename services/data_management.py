from __future__ import annotations

import base64
import json
import sqlite3
from datetime import UTC, date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from repository.database import DATABASE_URL

EXPORT_SCHEMA_VERSION = 1


def backup_database(
    destination_dir: str | Path = ".edgeiq_backups",
    *,
    database_url: str | None = None,
) -> dict:
    source_path = _sqlite_path(database_url or DATABASE_URL)
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC)
    backup_path = destination / f"edgeiq-{created_at.strftime('%Y%m%dT%H%M%SZ')}.db"

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
    source_path = _sqlite_path(database_url or DATABASE_URL)
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC)
    export_path = destination / f"edgeiq-export-{created_at.strftime('%Y%m%dT%H%M%SZ')}.json"

    with sqlite3.connect(source_path) as connection:
        connection.row_factory = sqlite3.Row
        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        tables = {
            row["name"]: [
                {key: _json_value(value) for key, value in dict(record).items()}
                for record in connection.execute(
                    f"SELECT * FROM {_quote_identifier(row['name'])}"
                ).fetchall()
            ]
            for row in table_rows
        }

    payload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "created_at": created_at.isoformat(),
        "source": "EdgeIQ",
        "tables": tables,
    }
    export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return {
        "created_at": created_at.isoformat(),
        "path": str(export_path.resolve()),
        "bytes": export_path.stat().st_size,
        "format": "json",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "tables": {name: len(rows) for name, rows in tables.items()},
    }


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


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'
