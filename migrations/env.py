import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from repository.database import Base
from repository.entities import BetEntity  # noqa: F401
from repository.models.bankroll_transaction_model import BankrollTransactionModel  # noqa: F401
from repository.models.entry_model import EntryModel  # noqa: F401
from repository.models.entry_prop_model import EntryPropModel  # noqa: F401
from repository.models.final_player_stat_model import FinalPlayerStatModel  # noqa: F401
from repository.models.plausibility_rejection_model import PlausibilityRejectionModel  # noqa: F401
from repository.models.player_identity_model import PlayerAliasModel, PlayerIdentityModel  # noqa: F401
from repository.models.prediction_record_model import PredictionRecordModel  # noqa: F401
from repository.models.prop_line_history_model import PropLineHistoryModel  # noqa: F401
from repository.models.product_event_model import ProductEventModel  # noqa: F401
from repository.models.recommendation_snapshot_model import RecommendationSnapshotModel  # noqa: F401
from repository.models.research_evidence_model import ResearchEvidenceModel  # noqa: F401
from repository.models.research_session_model import ResearchSessionModel  # noqa: F401
from repository.models.settings_model import SettingsModel  # noqa: F401
from repository.models.settlement_audit_model import SettlementAuditModel  # noqa: F401
from repository.models.shadow_prediction_model import ShadowPredictionModel  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating an engine."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
