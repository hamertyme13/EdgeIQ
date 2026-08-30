from repository.models.background_job_model import BackgroundJobModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.plausibility_rejection_model import PlausibilityRejectionModel
from repository.models.player_feature_model import PlayerFeatureModel
from repository.models.prediction_record_model import PredictionRecordModel
from repository.models.recommendation_snapshot_model import RecommendationSnapshotModel
from repository.models.shadow_prediction_model import ShadowPredictionModel


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


def test_entry_leg_schema_preserves_exact_provider_identity() -> None:
    columns = set(EntryPropModel.__table__.columns.keys())

    assert {"provider_event_id", "provider_offer_id"} <= columns


def test_player_feature_schema_materializes_verified_history() -> None:
    columns = set(PlayerFeatureModel.__table__.columns.keys())
    assert {"feature_key", "normalized_player_key", "history_json", "summary_json", "materialized_at"} <= columns


def test_background_job_schema_preserves_restart_safe_progress() -> None:
    columns = set(BackgroundJobModel.__table__.columns.keys())
    assert {
        "job_id", "dedupe_key", "status", "progress", "phase", "result_json", "error",
        "owner_id", "process_id", "heartbeat_at",
    } <= columns
