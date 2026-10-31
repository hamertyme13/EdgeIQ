"""Copy a closed SQLite backup into an empty, migrated PostgreSQL database.

The desktop database is never modified. Keep the desktop on SQLite until a
separate maintenance-window cutover reconciles writes after the backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
LEDGER_TABLES = ("entries", "entry_props", "settlement_audits", "bets")


def _source_connection(path: Path) -> sqlite3.Connection:
    source = path.resolve(strict=True)
    if source == (ROOT / "edgeiq.db").resolve():
        raise ValueError("Use a separate, completed SQLite backup, not the live desktop database.")
    if Path(f"{source}-wal").exists():
        raise ValueError("The backup has a WAL file; finish and close the backup before importing.")
    connection = sqlite3.connect(f"file:{quote(str(source), safe='/')}?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _source_tables(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    names = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    return {
        name: tuple(row[1] for row in connection.execute(f"PRAGMA table_info({quote_identifier(name)})"))
        for name in names
    }


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _copy_order(connection: sqlite3.Connection, names: set[str]) -> list[str]:
    dependencies = {
        name: {row[2] for row in connection.execute(f"PRAGMA foreign_key_list({quote_identifier(name)})")}
        & names
        for name in names
    }
    dependencies.pop("alembic_version", None)
    ordered: list[str] = []
    while dependencies:
        ready = sorted(name for name, parents in dependencies.items() if not parents - set(ordered))
        if not ready:
            raise ValueError("Foreign-key cycle in source; automatic copy order is unsafe.")
        ordered.extend(ready)
        for name in ready:
            del dependencies[name]
    return ordered


def _ledger_digest(connection, table: str, columns: tuple[str, ...], *, postgres: bool) -> str:
    digest = hashlib.sha256()
    query = sql.SQL("SELECT {} FROM {} ORDER BY id").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table)
    ) if postgres else f"SELECT {', '.join(map(quote_identifier, columns))} FROM {quote_identifier(table)} ORDER BY id"
    cursor = connection.cursor()
    cursor.execute(query)
    while rows := cursor.fetchmany(1000):
        for row in rows:
            normalized = [
                int(value) if isinstance(value, bool) else
                datetime.fromisoformat(value).isoformat(sep=" ", timespec="microseconds")
                if isinstance(value, str) and column.endswith("_at") else
                value.isoformat(sep=" ", timespec="microseconds")
                if isinstance(value, datetime) else value
                for column, value in zip(columns, row, strict=True)
            ]
            digest.update(json.dumps(normalized, default=str, ensure_ascii=False, separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _target_columns(connection: psycopg.Connection) -> dict[str, tuple[str, ...]]:
    rows = connection.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema='public' ORDER BY table_name, ordinal_position"
    ).fetchall()
    result: dict[str, list[str]] = {}
    for table, column in rows:
        result.setdefault(table, []).append(column)
    return {table: tuple(columns) for table, columns in result.items()}


def _check_target(source: sqlite3.Connection, target: psycopg.Connection, tables: dict[str, tuple[str, ...]]) -> list[str]:
    target_tables = _target_columns(target)
    if set(tables) != set(target_tables):
        raise ValueError(f"Schema table mismatch: source-only={sorted(set(tables) - set(target_tables))}, "
                         f"target-only={sorted(set(target_tables) - set(tables))}")
    for table, columns in tables.items():
        if set(columns) != set(target_tables[table]):
            raise ValueError(f"Column mismatch in {table}; run migrations on both databases first.")
    source_revision = source.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    target_revision = target.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    if source_revision != target_revision:
        raise ValueError(f"Alembic revisions differ: SQLite={source_revision}, PostgreSQL={target_revision}.")
    order = _copy_order(source, set(tables))
    for table in order:
        exists = target.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM {} LIMIT 1)").format(sql.Identifier(table))).fetchone()[0]
        if exists:
            raise ValueError(f"PostgreSQL target is not empty: {table} contains data.")
    return order


def _sync_sequences(target: psycopg.Connection, table: str) -> None:
    rows = target.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_default LIKE 'nextval(%%'",
        (table,),
    ).fetchall()
    for (column,) in rows:
        target.execute(
            sql.SQL("SELECT setval(pg_get_serial_sequence(%s, %s), "
                    "COALESCE((SELECT MAX({column}) FROM {table}), 1), "
                    "EXISTS(SELECT 1 FROM {table}))").format(
                column=sql.Identifier(column), table=sql.Identifier(table)
            ),
            (f"public.{quote_identifier(table)}", column),
        )


def migrate(source_path: Path, target_url: str, *, execute: bool = False) -> dict:
    if not target_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Target must be a PostgreSQL connection URL.")
    with _source_connection(source_path) as source, psycopg.connect(target_url) as target:
        tables = _source_tables(source)
        order = _check_target(source, target, tables)
        result = {"source": str(source_path.resolve()), "revision": source.execute(
            "SELECT version_num FROM alembic_version").fetchone()[0],
            "tables": len(order), "mode": "copy" if execute else "dry-run"}
        if not execute:
            target.rollback()
            return result
        source.execute("BEGIN")
        counts: dict[str, int] = {}
        for table in order:
            columns = tables[table]
            query = f"SELECT {', '.join(map(quote_identifier, columns))} FROM {quote_identifier(table)}"
            copy_query = sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
            )
            count = 0
            with target.cursor() as cursor, cursor.copy(copy_query) as copy:
                for row in source.execute(query):
                    copy.write_row(row)
                    count += 1
                    if count % 100_000 == 0:
                        print(f"Copying {table}: {count} rows", flush=True)
            _sync_sequences(target, table)
            actual = target.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            if actual != count:
                raise ValueError(f"Row count mismatch for {table}: SQLite={count}, PostgreSQL={actual}.")
            counts[table] = count
            print(f"Copied {table}: {count} rows", flush=True)
        for table in LEDGER_TABLES:
            if table in tables and "id" in tables[table]:
                source_digest = _ledger_digest(source, table, tables[table], postgres=False)
                target_digest = _ledger_digest(target, table, tables[table], postgres=True)
                if source_digest != target_digest:
                    raise ValueError(f"Ledger content differs for {table}; PostgreSQL copy rolled back.")
        target.commit()
        source.commit()
        result["counts"] = counts
        result["ledger_reconciled"] = True
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Completed, separate SQLite backup")
    parser.add_argument("--execute", action="store_true", help="Copy only into an empty PostgreSQL target")
    args = parser.parse_args()
    target_url = os.getenv("EDGEIQ_MIGRATION_TARGET_URL", "")
    if not target_url:
        parser.error("Set EDGEIQ_MIGRATION_TARGET_URL; credentials are never accepted on the command line.")
    try:
        report = migrate(args.source, target_url, execute=args.execute)
    except (OSError, ValueError, sqlite3.Error, psycopg.Error) as exc:
        parser.exit(1, f"Migration stopped: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
