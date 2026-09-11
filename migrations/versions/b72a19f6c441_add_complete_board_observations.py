"""add complete board observations

Revision ID: b72a19f6c441
Revises: f92d4a61c830
Create Date: 2026-08-22 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b72a19f6c441"
down_revision: str | Sequence[str] | None = "f92d4a61c830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Desktop startup may create additive model tables before Alembic runs.
    # In that case Alembic still needs to advance the revision safely.
    if "board_offer_observations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "board_offer_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_key", sa.String(), nullable=False),
        sa.Column("market_key", sa.String(), nullable=False),
        sa.Column("offer_key", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_offer_id", sa.String(), server_default=""),
        sa.Column("provider_player_id", sa.String(), server_default=""),
        sa.Column("player_identity_id", sa.Integer()),
        sa.Column("normalized_player_key", sa.String(), nullable=False),
        sa.Column("player", sa.String(), nullable=False),
        sa.Column("team", sa.String(), server_default=""),
        sa.Column("opponent", sa.String(), server_default=""),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("stat", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("opening_line", sa.Float()),
        sa.Column("closing_line", sa.Float()),
        sa.Column("offer_type", sa.String(), nullable=False, server_default="standard"),
        sa.Column("payout_multiplier", sa.Float()),
        sa.Column("game_id", sa.String(), server_default=""),
        sa.Column("game", sa.String(), server_default=""),
        sa.Column("scheduled_start", sa.String(), server_default=""),
        sa.Column("home_away", sa.String(), server_default=""),
        sa.Column("rest_days", sa.Float()),
        sa.Column("projection", sa.Float()),
        sa.Column("probability", sa.Float()),
        sa.Column("expected_minutes", sa.Float()),
        sa.Column("expected_opportunities", sa.Float()),
        sa.Column("model_version", sa.String(), server_default=""),
        sa.Column("feature_snapshot", sa.Text(), server_default=""),
        sa.Column("context_snapshot", sa.Text(), server_default=""),
        sa.Column("provider_payload", sa.Text(), server_default=""),
        sa.Column("eligibility_status", sa.String(), server_default="unreviewed"),
        sa.Column("eligibility_reason", sa.Text(), server_default=""),
        sa.Column("actual", sa.Float()),
        sa.Column("outcome", sa.String(), server_default=""),
        sa.Column("outcome_source", sa.String(), server_default=""),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("analyzed_at", sa.DateTime()),
        sa.Column("settled_at", sa.DateTime()),
        sa.UniqueConstraint("observation_key", name="uq_board_offer_observation_key"),
    )
    for column in (
        "market_key", "offer_key", "provider", "provider_offer_id", "provider_player_id",
        "player_identity_id", "normalized_player_key", "sport", "stat", "game_id",
        "scheduled_start", "eligibility_status", "outcome", "captured_at",
    ):
        op.create_index(f"ix_board_offer_observations_{column}", "board_offer_observations", [column])


def downgrade() -> None:
    op.drop_table("board_offer_observations")
