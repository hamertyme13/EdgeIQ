from concurrent.futures import ThreadPoolExecutor

import pytest

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
