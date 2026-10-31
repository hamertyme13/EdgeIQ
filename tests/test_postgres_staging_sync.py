import sqlite3
from datetime import datetime

from scripts.sync_postgres_staging import _postgres_value, changed_rows


def test_changed_rows_distinguishes_inserts_updates_and_deletes():
    with sqlite3.connect(":memory:") as old, sqlite3.connect(":memory:") as new:
        for connection in (old, new):
            connection.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, status TEXT)")
        old.executemany("INSERT INTO entries VALUES (?, ?)", [(1, "Pending"), (2, "Pending"), (4, "Loss")])
        new.executemany("INSERT INTO entries VALUES (?, ?)", [(1, "Settled"), (3, "Pending"), (4, "Loss")])

        assert list(changed_rows(old, new, "entries", ("id", "status"), "id")) == [
            ("update", (1, "Settled")),
            ("delete", (2, "Pending")),
            ("insert", (3, "Pending")),
        ]


def test_changed_rows_supports_text_primary_keys():
    with sqlite3.connect(":memory:") as old, sqlite3.connect(":memory:") as new:
        for connection in (old, new):
            connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        old.executemany("INSERT INTO settings VALUES (?, ?)", [("a", "old"), ("z", "same")])
        new.executemany("INSERT INTO settings VALUES (?, ?)", [("a", "new"), ("m", "added"), ("z", "same")])

        assert list(changed_rows(old, new, "settings", ("key", "value"), "key")) == [
            ("update", ("a", "new")),
            ("insert", ("m", "added")),
        ]


def test_update_values_use_postgres_types():
    assert _postgres_value(1, "boolean") is True
    assert _postgres_value(0, "boolean") is False
    assert _postgres_value("2026-10-27 10:20:00.000000", "timestamp without time zone") == datetime(
        2026, 10, 27, 10, 20,
    )
