import gzip
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from services.board_payload_archive import archive_board_payload_batch, restore_board_payload_batch
from services.data_management import backup_database


def test_board_payload_archive_is_bounded_reversible_and_preserves_outcomes(tmp_path: Path):
    database = tmp_path / "board.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE board_offer_observations (id INTEGER PRIMARY KEY, captured_at TEXT, "
            "provider_payload TEXT, outcome TEXT, projection REAL)"
        )
        connection.executemany(
            "INSERT INTO board_offer_observations VALUES (?, ?, ?, ?, ?)",
            [(1, "2026-08-01 12:00:00", '{"offer":1}', "Win", 22.0),
             (2, "2026-08-02 12:00:00", '{"offer":2}', "Loss", 14.0),
             (3, "2026-10-06 12:00:00", '{"offer":3}', "", None)],
        )
    url = f"sqlite:///{database}"
    options = {"database_url": url, "archive_dir": tmp_path / "archives", "limit": 1,
               "now": datetime(2026, 10, 7, tzinfo=UTC)}
    preview = archive_board_payload_batch(**options)
    assert preview["batch_rows"] == 1
    assert preview["cleared_payloads"] == 0
    with pytest.raises(ValueError, match="backup"):
        archive_board_payload_batch(**options, execute=True)
    backup = backup_database(tmp_path / "backups", database_url=url)
    result = archive_board_payload_batch(**options, execute=True, backup_path=backup["path"])
    assert result["cleared_payloads"] == 1
    with gzip.open(result["archived_path"], "rt", encoding="utf-8") as handle:
        assert json.loads(handle.readline())["provider_payload"] == '{"offer":1}'
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT outcome, projection, provider_payload FROM board_offer_observations WHERE id=1").fetchone() == ("Win", 22.0, "")
        assert connection.execute("SELECT provider_payload FROM board_offer_observations WHERE id=2").fetchone()[0] == '{"offer":2}'
    assert restore_board_payload_batch(result["archived_path"], database_url=url) == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT provider_payload FROM board_offer_observations WHERE id=1").fetchone()[0] == '{"offer":1}'
