from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine

from repository import database


def test_initialize_database_checks_schema_once_per_engine(monkeypatch):
    checked = []
    first_engine = object()
    second_engine = object()
    monkeypatch.setattr(database, "_initialized_engine", None)
    monkeypatch.setattr(database, "engine", first_engine)
    monkeypatch.setattr(database.Base.metadata, "create_all", lambda *, bind: checked.append(bind))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: database.initialize_database(), range(40)))

    assert checked == [first_engine]

    monkeypatch.setattr(database, "engine", second_engine)
    database.initialize_database()
    assert checked == [first_engine, second_engine]


def test_initialize_database_retries_after_schema_failure(monkeypatch):
    attempts = []
    test_engine = object()
    monkeypatch.setattr(database, "_initialized_engine", None)
    monkeypatch.setattr(database, "engine", test_engine)

    def create_all(*, bind):
        attempts.append(bind)
        if len(attempts) == 1:
            raise RuntimeError("schema unavailable")

    monkeypatch.setattr(database.Base.metadata, "create_all", create_all)

    with pytest.raises(RuntimeError, match="schema unavailable"):
        database.initialize_database()
    database.initialize_database()

    assert attempts == [test_engine, test_engine]


def test_sqlite_initialization_enables_wal_for_new_database(monkeypatch, tmp_path):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(database, "_initialized_engine", None)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database.Base.metadata, "create_all", lambda *, bind: None)

    database.initialize_database()
    with test_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    test_engine.dispose()
