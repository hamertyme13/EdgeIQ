import sqlite3

import pytest

from scripts.migrate_sqlite_to_postgres import _copy_order, _source_connection, quote_identifier


def test_copy_order_respects_foreign_keys():
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        assert _copy_order(connection, {"child", "parent"}) == ["parent", "child"]


def test_copy_order_rejects_cycles():
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id))")
        connection.execute("CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id))")
        with pytest.raises(ValueError, match="cycle"):
            _copy_order(connection, {"a", "b"})


def test_source_connection_rejects_live_desktop_database(monkeypatch, tmp_path):
    from scripts import migrate_sqlite_to_postgres as migration

    (tmp_path / "edgeiq.db").touch()
    monkeypatch.setattr(migration, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="live desktop database"):
        _source_connection(tmp_path / "edgeiq.db")


def test_source_connection_rejects_unclosed_wal(tmp_path):
    source = tmp_path / "backup.sqlite"
    source.touch()
    (tmp_path / "backup.sqlite-wal").touch()
    with pytest.raises(ValueError, match="WAL file"):
        _source_connection(source)


def test_quote_identifier_escapes_quotes():
    assert quote_identifier('some"table') == '"some""table"'
