import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")

_ENGINE_ARGS = {"echo": False}

if DATABASE_URL.startswith("sqlite"):
    _ENGINE_ARGS["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(DATABASE_URL, **_ENGINE_ARGS)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cursor.close()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


def initialize_database():

    from repository.models.entry_model import EntryModel
    from repository.models.entry_prop_model import EntryPropModel
    from repository.models.final_player_stat_model import FinalPlayerStatModel
    from repository.models.settings_model import SettingsModel
    from repository.models.prop_line_history_model import PropLineHistoryModel
    from repository.models.bankroll_transaction_model import BankrollTransactionModel
    from repository.models.player_identity_model import PlayerAliasModel, PlayerIdentityModel
    from repository.models.settlement_audit_model import SettlementAuditModel
    from repository.entities import BetEntity

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations():
    """Run additive migrations that are safe to repeat for local SQLite data."""
    from sqlalchemy import text

    if not DATABASE_URL.startswith("sqlite"):
        return

    migrations = {
        "bets": [
            ("platform", "TEXT DEFAULT ''"),
            ("stat_type", "TEXT DEFAULT ''"),
            ("win_probability", "REAL DEFAULT 0.0"),
            ("source", "TEXT DEFAULT 'manual'"),
            ("source_entry_id", "INTEGER"),
            ("entry_mode", "TEXT DEFAULT 'real'"),
            ("payout_type", "TEXT DEFAULT 'standard'"),
            ("payout_table_snapshot", "TEXT DEFAULT ''"),
            ("expected_return", "REAL DEFAULT 0.0"),
            ("expected_value", "REAL DEFAULT 0.0"),
            ("created_at", "DATETIME"),
        ],
        "entries": [
            ("status", "TEXT DEFAULT 'Draft'"),
            ("result", "TEXT DEFAULT ''"),
            ("placed_at", "DATETIME"),
            ("settled_at", "DATETIME"),
            ("wager", "REAL DEFAULT 0.0"),
            ("multiplier", "REAL DEFAULT 1.0"),
            ("potential_payout", "REAL DEFAULT 0.0"),
            ("profit", "REAL DEFAULT 0.0"),
            ("recommended_by_app", "BOOLEAN DEFAULT 0"),
            ("audit_snapshot", "TEXT DEFAULT ''"),
            ("entry_mode", "TEXT DEFAULT 'real'"),
            ("payout_type", "TEXT DEFAULT 'standard'"),
            ("payout_table_snapshot", "TEXT DEFAULT ''"),
            ("expected_return", "REAL DEFAULT 0.0"),
            ("expected_value", "REAL DEFAULT 0.0"),
        ],
        "entry_props": [
            ("platform", "TEXT DEFAULT ''"),
            ("player_identity_id", "INTEGER"),
            ("player_provider", "TEXT DEFAULT ''"),
            ("provider_player_id", "TEXT DEFAULT ''"),
            ("game", "TEXT DEFAULT ''"),
            ("game_time", "TEXT DEFAULT ''"),
            ("position", "TEXT DEFAULT ''"),
            ("baseline_line", "REAL"),
            ("standard_line", "REAL"),
            ("line_offer_type", "TEXT DEFAULT 'standard'"),
            ("adjusted_line", "BOOLEAN DEFAULT 0"),
            ("is_discounted_line", "BOOLEAN DEFAULT 0"),
            ("is_premium_line", "BOOLEAN DEFAULT 0"),
            ("line_discount", "REAL DEFAULT 0.0"),
            ("projection_source", "TEXT DEFAULT ''"),
            ("auto_projected", "BOOLEAN DEFAULT 0"),
            ("direction", "TEXT DEFAULT 'Over'"),
            ("actual", "REAL"),
            ("final_result", "TEXT DEFAULT ''"),
            ("final_source", "TEXT DEFAULT ''"),
            ("final_status", "TEXT DEFAULT ''"),
        ],
        "final_player_stats": [
            ("status", "TEXT DEFAULT 'played'"),
            ("player_identity_id", "INTEGER"),
            ("player_provider", "TEXT DEFAULT ''"),
            ("provider_player_id", "TEXT DEFAULT ''"),
        ],
        "prop_line_history": [
            ("game", "TEXT DEFAULT ''"),
            ("game_time", "TEXT DEFAULT ''"),
            ("line_offer_type", "TEXT DEFAULT 'standard'"),
        ],
    }

    with engine.connect() as conn:
        for table_name, columns in migrations.items():
            result = conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result.fetchall()}

            if not existing:
                continue

            for column_name, typedef in columns:
                if column_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {typedef}")
                    )
            if table_name == "bets" and "created_at" not in existing:
                conn.execute(text("UPDATE bets SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        conn.commit()
