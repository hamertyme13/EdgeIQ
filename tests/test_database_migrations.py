from sqlalchemy import create_engine, inspect, text

import repository.database as database
from repository.models.prediction_record_model import PredictionRecordModel


def test_lightweight_migrations_upgrade_legacy_entries_table(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE entries (id INTEGER PRIMARY KEY, platform TEXT)"))

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.db'}")
    database._run_lightweight_migrations()

    columns = {column["name"] for column in inspect(engine).get_columns("entries")}
    assert {"status", "result", "audit_snapshot", "entry_mode", "expected_value"} <= columns


def test_prediction_ledger_schema_has_immutable_prediction_and_outcome_fields() -> None:
    columns = set(PredictionRecordModel.__table__.columns.keys())

    assert {
        "independent_market_key",
        "offer_key",
        "model_version",
        "feature_snapshot",
        "probability",
        "legacy_quarantined",
        "outcome",
        "outcome_source",
    } <= columns
