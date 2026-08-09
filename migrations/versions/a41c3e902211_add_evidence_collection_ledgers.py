"""add evidence collection ledgers

Revision ID: a41c3e902211
Revises: f638c5b72379
Create Date: 2026-08-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a41c3e902211"
down_revision: str | Sequence[str] | None = "f638c5b72379"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_recommendation_snapshot_id"),
    )
    op.create_index("ix_recommendation_snapshots_snapshot_id", "recommendation_snapshots", ["snapshot_id"])
    op.create_index("ix_recommendation_snapshots_model_version", "recommendation_snapshots", ["model_version"])
    op.create_index("ix_recommendation_snapshots_platform", "recommendation_snapshots", ["platform"])
    op.create_index("ix_recommendation_snapshots_sport", "recommendation_snapshots", ["sport"])
    op.create_index("ix_recommendation_snapshots_purpose", "recommendation_snapshots", ["purpose"])
    op.create_index("ix_recommendation_snapshots_captured_at", "recommendation_snapshots", ["captured_at"])

    op.create_table(
        "shadow_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cohort_date", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("independent_market_key", sa.String(), nullable=False),
        sa.Column("player", sa.String(), nullable=False),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("stat", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("game", sa.String(), nullable=True),
        sa.Column("game_time", sa.String(), nullable=True),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("projection", sa.Float(), nullable=True),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("feature_snapshot", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("actual", sa.Float(), nullable=True),
        sa.Column("outcome_source", sa.String(), nullable=True),
        sa.Column("settlement_attempts", sa.Integer(), nullable=False),
        sa.Column("last_settlement_error", sa.Text(), nullable=True),
        sa.Column("predicted_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cohort_date", "model_version", "independent_market_key", name="uq_shadow_cohort_market"),
    )
    for column in ("cohort_date", "model_version", "independent_market_key", "sport", "stat", "platform", "status"):
        op.create_index(f"ix_shadow_predictions_{column}", "shadow_predictions", [column])


def downgrade() -> None:
    op.drop_table("shadow_predictions")
    op.drop_table("recommendation_snapshots")
