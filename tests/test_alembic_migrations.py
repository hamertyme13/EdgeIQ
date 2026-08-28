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
        entry_prop_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(entry_props)")
        }

    assert {
        "alembic_version",
        "entries",
        "entry_props",
        "prediction_records",
        "settlement_audits",
        "player_identities",
        "player_aliases",
        "research_evidence",
    } <= tables
    assert {"payout_type", "payout_table_snapshot", "expected_return", "expected_value"} <= bet_columns
    assert {"provider_event_id", "provider_offer_id"} <= entry_prop_columns


def test_alembic_can_downgrade_to_base_and_upgrade_again(tmp_path: Path) -> None:
    database_path = tmp_path / "alembic-roundtrip.db"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    root = Path(__file__).parents[1]

    for command in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            check=True,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
        )

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        evidence_exists = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'research_evidence'"
        ).fetchone()[0]
        product_events_exist = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'product_events'"
        ).fetchone()[0]
        research_sessions_exist = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'research_sessions'"
        ).fetchone()[0]
        board_observations_exist = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'board_offer_observations'"
        ).fetchone()[0]

    assert revision == "d94e7f31a205"
    assert evidence_exists == 1
    assert product_events_exist == 1
    assert research_sessions_exist == 1
    assert board_observations_exist == 1
