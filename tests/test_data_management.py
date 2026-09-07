import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

import services.data_management as data_management
from services.data_management import backup_database, compact_board_history, export_database


def _database(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, result TEXT)")
        connection.execute("INSERT INTO evidence (result) VALUES ('Win')")
        connection.commit()
    return path, f"sqlite:///{path}"


def test_backup_database_creates_consistent_copy(tmp_path: Path) -> None:
    _, database_url = _database(tmp_path)

    result = backup_database(tmp_path / "backups", database_url=database_url)

    backup_path = Path(result["path"])
    assert backup_path.exists()
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("SELECT result FROM evidence").fetchone()[0] == "Win"


def test_backup_database_uses_unique_names(tmp_path: Path) -> None:
    _, database_url = _database(tmp_path)

    first = backup_database(tmp_path / "backups", database_url=database_url)
    second = backup_database(tmp_path / "backups", database_url=database_url)

    assert first["path"] != second["path"]


def test_backup_database_fails_before_copy_when_storage_is_low(tmp_path: Path, monkeypatch) -> None:
    _, database_url = _database(tmp_path)
    monkeypatch.setattr(
        data_management.shutil,
        "disk_usage",
        lambda _path: type("DiskUsage", (), {"free": 1})(),
    )

    with pytest.raises(OSError, match="Free storage or choose another backup destination"):
        backup_database(tmp_path / "backups", database_url=database_url)

    assert list((tmp_path / "backups").glob("*.db")) == []


def test_backup_database_rejects_overlapping_maintenance(tmp_path: Path, monkeypatch) -> None:
    _, database_url = _database(tmp_path)

    @contextmanager
    def unavailable(_name):
        yield False

    monkeypatch.setattr(data_management, "named_operation_lock", unavailable)

    with pytest.raises(ValueError, match="maintenance task is already running"):
        backup_database(tmp_path / "backups", database_url=database_url)


def test_export_database_writes_versioned_json(tmp_path: Path) -> None:
    _, database_url = _database(tmp_path)

    result = export_database(tmp_path / "exports", database_url=database_url)

    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tables"]["evidence"] == [{"id": 1, "result": "Win"}]
    assert result["tables"] == {"evidence": 1}
    assert list((tmp_path / "exports").glob("*.partial")) == []


def test_export_database_streams_multiple_batches(tmp_path: Path) -> None:
    path, database_url = _database(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO evidence (result) VALUES (?)",
            [(f"Result {index}",) for index in range(1, 1201)],
        )
        connection.commit()

    result = export_database(tmp_path / "exports", database_url=database_url)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["tables"]["evidence"] == 1201
    assert len(payload["tables"]["evidence"]) == 1201
    assert payload["tables"]["evidence"][-1]["result"] == "Result 1200"


def test_export_database_fails_before_write_when_storage_is_low(tmp_path: Path, monkeypatch) -> None:
    _, database_url = _database(tmp_path)
    monkeypatch.setattr(
        data_management.shutil,
        "disk_usage",
        lambda _path: type("DiskUsage", (), {"free": 1})(),
    )

    with pytest.raises(OSError, match="Free storage or choose another export destination"):
        export_database(tmp_path / "exports", database_url=database_url)

    assert list((tmp_path / "exports").iterdir()) == []


def _board_history_database(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "board-history.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE board_offer_observations (
                id INTEGER PRIMARY KEY,
                offer_key TEXT NOT NULL,
                market_key TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                analyzed_at TEXT,
                settled_at TEXT,
                outcome TEXT,
                projection REAL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO board_offer_observations
                (id, offer_key, market_key, captured_at, analyzed_at, settled_at, outcome, projection)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "offer-a", "market-a", "2026-09-06T10:00:00", None, None, "", None),
                (2, "offer-a", "market-a", "2026-09-06T10:10:00", None, None, "", None),
                (3, "offer-a", "market-a", "2026-09-06T10:20:00", None, None, "", None),
                (4, "offer-a", "market-a", "2026-09-06T11:00:00", None, None, "", None),
                (5, "offer-b", "market-b", "2026-09-06T10:00:00", None, None, "", None),
                (6, "offer-b", "market-b", "2026-09-06T10:10:00", "2026-09-06T10:11:00", None, "", None),
                (7, "offer-b", "market-b", "2026-09-06T10:20:00", None, None, "Win", None),
                (8, "offer-b", "market-b", "2026-09-06T10:30:00", None, None, "", 18.4),
                (9, "offer-b", "market-b", "2026-09-06T10:40:00", None, None, "", None),
            ],
        )
        connection.commit()
    return path, f"sqlite:///{path}"


def test_compact_board_history_previews_without_mutating(tmp_path: Path) -> None:
    path, database_url = _board_history_database(tmp_path)

    result = compact_board_history(database_url=database_url)

    assert result["eligible"] == 2
    assert result["removed"] == 0
    assert result["backup"] is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM board_offer_observations").fetchone()[0] == 9


def test_compact_board_history_backs_up_and_preserves_evidence(tmp_path: Path) -> None:
    path, database_url = _board_history_database(tmp_path)

    result = compact_board_history(
        execute=True,
        database_url=database_url,
        backup_destination=tmp_path / "backups",
    )

    assert result["eligible"] == 2
    assert result["removed"] == 2
    assert result["after"] == 7
    assert Path(result["backup"]["path"]).exists()
    with sqlite3.connect(path) as connection:
        remaining = {row[0] for row in connection.execute("SELECT id FROM board_offer_observations")}
    assert remaining == {1, 4, 5, 6, 7, 8, 9}
