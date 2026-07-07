import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")

_ENGINE_ARGS = {"echo": False}

if DATABASE_URL.startswith("sqlite"):
    _ENGINE_ARGS["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_ENGINE_ARGS)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


def initialize_database():

    from repository.models.entry_model import EntryModel
    from repository.models.entry_prop_model import EntryPropModel
    from repository.models.settings_model import SettingsModel
    from repository.models.prop_line_history_model import PropLineHistoryModel

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
        conn.commit()
