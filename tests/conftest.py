from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_DATABASE_DIR = Path(tempfile.mkdtemp(prefix="edgeiq-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATABASE_DIR / 'edgeiq-test.db'}"

from repository.database import SessionLocal, initialize_database

initialize_database()


@pytest.fixture(autouse=True)
def disable_billable_actor_runs(monkeypatch):
    monkeypatch.delenv("EDGEIQ_SLEEPER_APIFY_ENABLED", raising=False)
    monkeypatch.delenv("EDGEIQ_UNDERDOG_APIFY_ENABLED", raising=False)


@pytest.fixture()
def db_session():
    """Yield a SQLAlchemy session wrapped in a savepoint that is rolled back after each test.

    This keeps every test isolated — writes made inside the test are never
    committed to the shared on-disk database, so tests cannot pollute each other.
    """
    connection = SessionLocal.kw["bind"].connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    # Use a nested savepoint so that explicit session.commit() calls inside
    # application code do not permanently flush data.
    connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def pytest_sessionfinish(session, exitstatus) -> None:
    from repository.database import engine

    engine.dispose()
    shutil.rmtree(_TEST_DATABASE_DIR, ignore_errors=True)
