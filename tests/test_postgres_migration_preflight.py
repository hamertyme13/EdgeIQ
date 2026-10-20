import sqlite3
import subprocess

from scripts.postgres_migration_preflight import inspect_local_postgres, inspect_sqlite


def test_sqlite_preflight_counts_without_writing(tmp_path) -> None:
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE entry_props (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO entries VALUES (1)")
        connection.execute("INSERT INTO alembic_version VALUES ('test-head')")

    report = inspect_sqlite(path)

    assert report["critical_counts"]["entries"] == 1
    assert report["critical_counts"]["entry_props"] == 0
    assert report["critical_counts"]["final_player_stats"] is None
    assert report["alembic_revision"] == "test-head"
    assert report["changed_during_scan"] is False
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM entries").fetchone()[0] == 1


def test_postgres_preflight_requires_local_credentials(tmp_path) -> None:
    assert inspect_local_postgres(tmp_path)["status"] == "unavailable"


def test_postgres_preflight_distinguishes_empty_and_populated(monkeypatch, tmp_path) -> None:
    (tmp_path / ".edgeiq_local_postgres.env").write_text("local test fixture", encoding="ascii")

    def result(_command, **_kwargs):
        return subprocess.CompletedProcess([], 0, "head|0|0|0|0\n", "")

    monkeypatch.setattr(subprocess, "run", result)
    assert inspect_local_postgres(tmp_path)["status"] == "empty"

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "head|1|2|3|4\n", ""))
    report = inspect_local_postgres(tmp_path)
    assert report["status"] == "contains_data"
    assert report["critical_counts"]["entries"] == 1
