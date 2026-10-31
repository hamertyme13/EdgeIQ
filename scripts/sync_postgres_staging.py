"""Advance an isolated PostgreSQL copy from one closed SQLite backup to another.

The old backup must exactly match the current staging copy. The desktop's live
SQLite database is never opened or modified by this command.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migrate_sqlite_to_postgres import (
    LEDGER_TABLES,
    _copy_order,
    _ledger_digest,
    _source_connection,
    _source_tables,
    _sync_sequences,
    _target_columns,
    quote_identifier,
)


def changed_rows(
    old: sqlite3.Connection, new: sqlite3.Connection, table: str,
    columns: tuple[str, ...], key: str,
):
    query = (
        f"SELECT {', '.join(map(quote_identifier, columns))} "
        f"FROM {quote_identifier(table)} ORDER BY {quote_identifier(key)}"
    )
    position = columns.index(key)
    old_rows = iter(old.execute(query))
    new_rows = iter(new.execute(query))
    old_row = next(old_rows, None)
    new_row = next(new_rows, None)
    while old_row is not None or new_row is not None:
        if old_row is None or (new_row is not None and new_row[position] < old_row[position]):
            yield "insert", new_row
            new_row = next(new_rows, None)
        elif new_row is None or old_row[position] < new_row[position]:
            yield "delete", old_row
            old_row = next(old_rows, None)
        else:
            if old_row != new_row:
                yield "update", new_row
            old_row = next(old_rows, None)
            new_row = next(new_rows, None)


def _key_columns(source: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = source.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return tuple(row[1] for row in sorted(rows, key=lambda row: row[5]) if row[5])


def _verify_source_pair(
    old: sqlite3.Connection, new: sqlite3.Connection,
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    old_tables = _source_tables(old)
    new_tables = _source_tables(new)
    if old_tables != new_tables:
        raise ValueError("SQLite backup schemas differ; apply migrations before synchronizing.")
    old_revision = old.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    new_revision = new.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    if old_revision != new_revision:
        raise ValueError("SQLite backup Alembic revisions differ.")
    for table in old_tables:
        if table != "alembic_version" and len(_key_columns(old, table)) != 1:
            raise ValueError(f"Expected one primary key for {table}; manual migration required.")
    return old_tables, _copy_order(new, set(new_tables))


def _verify_baseline(old: sqlite3.Connection, target: psycopg.Connection, tables: dict) -> None:
    target_tables = _target_columns(target)
    if set(tables) != set(target_tables):
        raise ValueError("PostgreSQL staging tables do not match the SQLite backup.")
    for table, columns in tables.items():
        if set(columns) != set(target_tables[table]):
            raise ValueError(f"PostgreSQL staging columns differ for {table}.")
    revision = old.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    if target.execute("SELECT version_num FROM alembic_version").fetchone()[0] != revision:
        raise ValueError("PostgreSQL staging revision differs from the old backup.")
    for table in tables:
        if table == "alembic_version":
            continue
        source_count = old.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0]
        target_count = target.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
        if source_count != target_count:
            raise ValueError(f"PostgreSQL staging is not at the old backup: {table} count differs.")
    for table in LEDGER_TABLES:
        if table in tables and "id" in tables[table] and (
            _ledger_digest(old, table, tables[table], postgres=False)
            != _ledger_digest(target, table, tables[table], postgres=True)
        ):
            raise ValueError(f"PostgreSQL staging ledger differs from old backup: {table}.")


def _apply_inserts(
    old: sqlite3.Connection, new: sqlite3.Connection, target: psycopg.Connection,
    table: str, columns: tuple[str, ...], key: str,
) -> int:
    copy_query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    count = 0
    with target.cursor() as cursor, cursor.copy(copy_query) as copy:
        for kind, row in changed_rows(old, new, table, columns, key):
            if kind == "insert":
                copy.write_row(row)
                count += 1
    _sync_sequences(target, table)
    return count


def _apply_updates_and_collect_deletes(
    old: sqlite3.Connection, new: sqlite3.Connection, target: psycopg.Connection,
    table: str, columns: tuple[str, ...], key: str,
) -> tuple[int, list]:
    changed = tuple(column for column in columns if column != key)
    column_types = dict(target.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s", (table,),
    ).fetchall())
    update_query = sql.SQL("UPDATE {} SET {} WHERE {} = %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(column)) for column in changed),
        sql.Identifier(key),
    )
    position = columns.index(key)
    count = 0
    deletes = []
    with target.cursor() as cursor:
        for kind, row in changed_rows(old, new, table, columns, key):
            if kind == "delete":
                deletes.append(row[position])
            elif kind == "update":
                values = tuple(
                    _postgres_value(row[columns.index(column)], column_types[column])
                    for column in changed
                )
                cursor.execute(update_query, values + (row[position],))
                if cursor.rowcount != 1:
                    raise ValueError(f"Missing PostgreSQL row during {table} update: {row[position]}.")
                count += 1
    return count, deletes


def _postgres_value(value, data_type: str):
    if value is None:
        return None
    if data_type == "boolean":
        return bool(value)
    if data_type.startswith("timestamp") and isinstance(value, str):
        return datetime.fromisoformat(value)
    if data_type == "date" and isinstance(value, str):
        return date.fromisoformat(value)
    if data_type == "jsonb" and isinstance(value, str):
        return Jsonb(json.loads(value))
    return value


def sync(old_path: Path, new_path: Path, target_url: str, *, execute: bool = False) -> dict:
    if not target_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Target must be a PostgreSQL connection URL.")
    if old_path.resolve() == new_path.resolve():
        raise ValueError("Old and new backups must be different completed files.")
    with _source_connection(old_path) as old, _source_connection(new_path) as new, psycopg.connect(target_url) as target:
        tables, order = _verify_source_pair(old, new)
        _verify_baseline(old, target, tables)
        report = {"old_backup": str(old_path.resolve()), "new_backup": str(new_path.resolve()),
                  "tables": len(order), "mode": "sync" if execute else "dry-run"}
        if not execute:
            target.rollback()
            return report
        changes: dict[str, dict[str, int]] = {}
        deletions: dict[str, list] = {}
        for table in order:
            columns = tables[table]
            key = _key_columns(old, table)[0]
            added = _apply_inserts(old, new, target, table, columns, key)
            updated, deleted = _apply_updates_and_collect_deletes(old, new, target, table, columns, key)
            deletions[table] = deleted
            changes[table] = {"inserted": added, "updated": updated, "deleted": len(deleted)}
            if added or updated or deleted:
                print(f"Staged {table}: +{added} ~{updated} -{len(deleted)}", flush=True)
        for table in reversed(order):
            key = _key_columns(old, table)[0]
            delete_query = sql.SQL("DELETE FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(key))
            with target.cursor() as cursor:
                for value in deletions[table]:
                    cursor.execute(delete_query, (value,))
                    if cursor.rowcount != 1:
                        raise ValueError(f"Missing PostgreSQL row during {table} delete: {value}.")
        for table in order:
            source_count = new.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0]
            target_count = target.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            if source_count != target_count:
                raise ValueError(f"PostgreSQL row count differs after sync: {table}.")
        for table in LEDGER_TABLES:
            if table in tables and "id" in tables[table] and (
                _ledger_digest(new, table, tables[table], postgres=False)
                != _ledger_digest(target, table, tables[table], postgres=True)
            ):
                raise ValueError(f"PostgreSQL ledger differs after sync: {table}.")
        target.commit()
        report["changes"] = changes
        report["ledger_reconciled"] = True
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-backup", required=True, type=Path)
    parser.add_argument("--new-backup", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    target_url = os.getenv("EDGEIQ_MIGRATION_TARGET_URL", "")
    if not target_url:
        parser.error("Set EDGEIQ_MIGRATION_TARGET_URL; do not put credentials on the command line.")
    try:
        report = sync(args.old_backup, args.new_backup, target_url, execute=args.execute)
    except (OSError, ValueError, sqlite3.Error, psycopg.Error) as exc:
        parser.exit(1, f"Staging sync stopped: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
