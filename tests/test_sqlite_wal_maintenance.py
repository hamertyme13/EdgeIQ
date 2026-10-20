from sqlalchemy import create_engine

from services.sqlite_wal_maintenance import checkpoint_large_wal


def test_checkpoint_backfills_large_wal_before_last_connection_closes(tmp_path) -> None:
    database = tmp_path / "checkpoint.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("PRAGMA wal_autocheckpoint=100000")
        connection.exec_driver_sql("CREATE TABLE payloads (body TEXT)")
        for _ in range(50):
            connection.exec_driver_sql("INSERT INTO payloads VALUES (?)", ("x" * 4096,))

    assert not checkpoint_large_wal(engine, minimum_bytes=10**9)
    assert checkpoint_large_wal(engine, minimum_bytes=1)
    engine.dispose()


def test_memory_database_has_no_wal_file() -> None:
    engine = create_engine("sqlite:///:memory:")
    assert not checkpoint_large_wal(engine, minimum_bytes=0)
    engine.dispose()
