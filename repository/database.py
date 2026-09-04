import os
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")

_ENGINE_ARGS: dict[str, Any] = {"echo": False}

if DATABASE_URL.startswith("sqlite"):
    _ENGINE_ARGS["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    _ENGINE_ARGS.update({
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": int(os.getenv("EDGEIQ_DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("EDGEIQ_DB_MAX_OVERFLOW", "10")),
    })

engine = create_engine(DATABASE_URL, **_ENGINE_ARGS)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cursor.close()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base: Any = declarative_base()


def initialize_database():

    from repository.entities import BetEntity
    from repository.models.background_job_model import BackgroundJobModel
    from repository.models.bankroll_transaction_model import BankrollTransactionModel
    from repository.models.beta_feedback_model import BetaFeedbackModel
    from repository.models.beta_issue_model import BetaIssueModel
    from repository.models.beta_session_model import BetaSessionModel
    from repository.models.beta_user_model import BetaUserModel
    from repository.models.board_offer_observation_model import BoardOfferObservationModel
    from repository.models.entry_model import EntryModel
    from repository.models.entry_prop_model import EntryPropModel
    from repository.models.final_player_stat_model import FinalPlayerStatModel
    from repository.models.plausibility_rejection_model import PlausibilityRejectionModel
    from repository.models.player_feature_model import PlayerFeatureModel
    from repository.models.player_identity_model import PlayerAliasModel, PlayerIdentityModel
    from repository.models.prediction_record_model import PredictionRecordModel
    from repository.models.product_event_model import ProductEventModel
    from repository.models.prop_line_history_model import PropLineHistoryModel
    from repository.models.recommendation_snapshot_model import RecommendationSnapshotModel
    from repository.models.research_evidence_model import ResearchEvidenceModel
    from repository.models.research_session_model import ResearchSessionModel
    from repository.models.settings_model import SettingsModel
    from repository.models.settlement_audit_model import SettlementAuditModel
    from repository.models.shadow_prediction_model import ShadowPredictionModel

    Base.metadata.create_all(bind=engine)
