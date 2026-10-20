"""Read-only inventory before copying a desktop SQLite ledger to local PostgreSQL."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CRITICAL_TABLES = (
    "entries", "entry_props", "final_player_stats", "prediction_records",
    "board_offer_observations", "provider_offer_snapshots", "settlement_audits",
)


def inspect_sqlite(path: Path, *, query_seconds: float = 15.0) -> dict:
    source = path.resolve(strict=True)
    uri = f"file:{quote(str(source), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        connection.execute("PRAGMA query_only=ON")
        before = connection.execute("PRAGMA data_version").fetchone()[0]
        connection.execute("BEGIN")
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        counts: dict[str, int | None] = {}
        for table in CRITICAL_TABLES:
            if table not in tables:
                counts[table] = None
                continue
            deadline = time.monotonic() + query_seconds
            connection.set_progress_handler(lambda deadline=deadline: int(time.monotonic() > deadline), 10000)
            try:
                counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except sqlite3.OperationalError as exc:
                if "interrupted" not in str(exc).lower():
                    raise
                counts[table] = None
            finally:
                connection.set_progress_handler(None, 0)
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] if "alembic_version" in tables else None
        connection.commit()
        after = connection.execute("PRAGMA data_version").fetchone()[0]
    source_bytes = source.stat().st_size
    wal_path = Path(f"{source}-wal")
    free_bytes = shutil.disk_usage(source.parent).free
    return {
        "path": str(source), "database_bytes": source_bytes,
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "free_bytes": free_bytes,
        "space_for_separate_backup": free_bytes >= source_bytes * 1.2,
        "table_count": len(tables), "critical_counts": counts,
        "alembic_revision": revision,
        "changed_during_scan": before != after,
        "note": "Counts are from one read transaction. A timed-out or absent table is null; this does not certify a backup.",
    }


def inspect_local_postgres(root: Path) -> dict:
    env_file = root / ".edgeiq_local_postgres.env"
    if not env_file.exists():
        return {"status": "unavailable", "reason": "Local PostgreSQL credentials have not been created."}
    command = [
        "docker", "compose", "--env-file", str(env_file), "-f", str(root / "compose.postgres.yml"),
        "exec", "-T", "db", "psql", "-U", "edgeiq", "-d", "edgeiq", "-At", "-F", "|",
        "-c", "SELECT (SELECT version_num FROM alembic_version),"
        "(SELECT count(*) FROM entries),(SELECT count(*) FROM entry_props),"
        "(SELECT count(*) FROM final_player_stats),(SELECT count(*) FROM prediction_records)",
    ]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=20, check=True)
        revision, entries, props, final_stats, predictions = result.stdout.strip().split("|")
        counts = dict(zip(("entries", "entry_props", "final_player_stats", "prediction_records"),
                          map(int, (entries, props, final_stats, predictions)), strict=True))
        return {"status": "empty" if all(value == 0 for value in counts.values()) else "contains_data",
                "alembic_revision": revision, "critical_counts": counts}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "unavailable", "reason": "Local PostgreSQL could not be inspected."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=ROOT / "edgeiq.db")
    parser.add_argument("--query-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if args.query_seconds <= 0:
        parser.error("--query-seconds must be positive")
    report = {"sqlite": inspect_sqlite(args.sqlite, query_seconds=args.query_seconds),
              "local_postgres": inspect_local_postgres(ROOT)}
    report["ready_for_copy"] = False
    report["next_step"] = (
        "Verify a separate current SQLite backup and pause desktop writes before copying. "
        "Keep SQLite unchanged until row counts and entry outcomes reconcile."
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
