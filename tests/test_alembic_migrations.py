import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_upgrades_empty_database_to_current_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "alembic.db"
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database_path}",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        bet_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(bets)")
        }

    assert {
        "alembic_version",
        "entries",
        "entry_props",
        "prediction_records",
        "settlement_audits",
        "player_identities",
        "player_aliases",
    } <= tables
    assert {"payout_type", "payout_table_snapshot", "expected_return", "expected_value"} <= bet_columns
