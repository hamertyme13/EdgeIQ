import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")

engine = create_engine(
    DATABASE_URL,
    echo=False
)

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
    _migrate_bets_table()


def _migrate_bets_table():
    """Add columns introduced after initial schema — safe to run repeatedly."""
    import sqlite3 as _sqlite3
    from sqlalchemy import text

    new_columns = [
        ("platform",        "TEXT DEFAULT ''"),
        ("stat_type",       "TEXT DEFAULT ''"),
        ("win_probability", "REAL DEFAULT 0.0"),
    ]

    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(bets)"))
        existing = {row[1] for row in result.fetchall()}

    with engine.connect() as conn:
        for col, typedef in new_columns:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE bets ADD COLUMN {col} {typedef}"))
        conn.commit()

    