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
        product_event_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(product_events)")
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
        "player_features",
        "background_jobs",
        "beta_users",
        "beta_sessions",
        "beta_feedback",
        "beta_issues",
        "game_predictions",
    } <= tables
    assert {"payout_type", "payout_table_snapshot", "expected_return", "expected_value"} <= bet_columns
    assert {"provider_event_id", "provider_offer_id"} <= entry_prop_columns
    assert {"user_id", "session_id"} <= product_event_columns


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
        player_features_exist = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'player_features'"
        ).fetchone()[0]
        background_jobs_exist = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'background_jobs'"
        ).fetchone()[0]
        board_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(board_offer_observations)")
        }
        board_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(board_offer_observations)")
        }
        retry_index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_board_offer_pending_retry'"
        ).fetchone()[0]

    assert revision == "l65c9a3d8e42"
    assert evidence_exists == 1
    assert product_events_exist == 1
    assert research_sessions_exist == 1
    assert board_observations_exist == 1
    assert player_features_exist == 1
    assert background_jobs_exist == 1
    assert {
        "ix_board_offer_outcome_captured",
        "ix_board_offer_sport_captured",
        "ix_board_offer_market_captured",
        "ix_board_offer_provider_sport_start",
        "ix_board_offer_pending_retry",
        "ix_board_offer_analyzed",
    } <= board_indexes
    assert {
        "settlement_attempts",
        "last_settlement_attempt_at",
        "next_settlement_retry_at",
        "settlement_block_reason",
    } <= board_columns
    assert "WHERE outcome = '' AND next_settlement_retry_at IS NOT NULL" in retry_index_sql


def test_beta_migration_reconciles_tables_created_before_alembic_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "precreated-beta.db"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    root = Path(__file__).parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "g82d4f1a6b73"],
        check=True,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-c", "from repository.database import initialize_database; initialize_database()"],
        check=True,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )

    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        product_event_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(product_events)")
        }
        beta_table_count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name LIKE 'beta_%'"
        ).fetchone()[0]

    assert revision == "l65c9a3d8e42"
    assert beta_table_count == 4
    assert {"user_id", "session_id"} <= product_event_columns
