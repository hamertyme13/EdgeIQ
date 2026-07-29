import json
import sqlite3
from pathlib import Path

from services.data_management import backup_database, export_database


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


def test_export_database_writes_versioned_json(tmp_path: Path) -> None:
    _, database_url = _database(tmp_path)

    result = export_database(tmp_path / "exports", database_url=database_url)

    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tables"]["evidence"] == [{"id": 1, "result": "Win"}]
