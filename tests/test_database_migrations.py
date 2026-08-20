from sqlalchemy import create_engine, inspect, text

import repository.database as database
from repository.models.plausibility_rejection_model import PlausibilityRejectionModel
from repository.models.prediction_record_model import PredictionRecordModel
from repository.models.recommendation_snapshot_model import RecommendationSnapshotModel
from repository.models.shadow_prediction_model import ShadowPredictionModel


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


def test_evidence_collection_schema_has_dedicated_ledgers() -> None:
    shadow_columns = set(ShadowPredictionModel.__table__.columns.keys())
    snapshot_columns = set(RecommendationSnapshotModel.__table__.columns.keys())

    assert {"cohort_date", "model_version", "settlement_attempts", "outcome_source", "settled_at"} <= shadow_columns
    assert {"snapshot_id", "model_version", "platform", "sport", "purpose", "payload"} <= snapshot_columns


def test_plausibility_rejection_schema_preserves_diagnostics() -> None:
    columns = set(PlausibilityRejectionModel.__table__.columns.keys())

    assert {
        "rejection_reason",
        "original_provider_payload",
        "provider",
        "rejected_at",
        "normalized_value",
        "expected_minimum",
        "expected_maximum",
    } <= columns
