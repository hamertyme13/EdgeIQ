"""add game prediction ledger

Revision ID: j43a7e91c620
Revises: h31f8a2b7c04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j43a7e91c620"
down_revision: str | Sequence[str] | None = "h31f8a2b7c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "game_predictions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "game_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prediction_key", sa.String(160), nullable=False),
        sa.Column("sport", sa.String(20), nullable=False),
        sa.Column("game_id", sa.String(120), nullable=False),
        sa.Column("game", sa.String(240), nullable=False),
        sa.Column("home_team", sa.String(120), nullable=False),
        sa.Column("away_team", sa.String(120), nullable=False),
        sa.Column("game_start", sa.String(64), server_default=""),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("home_win_probability", sa.Float(), nullable=False),
        sa.Column("away_win_probability", sa.Float(), nullable=False),
        sa.Column("expected_margin", sa.Float(), nullable=False),
        sa.Column("expected_total", sa.Float(), nullable=False),
        sa.Column("expected_home_points", sa.Float(), nullable=False),
        sa.Column("expected_away_points", sa.Float(), nullable=False),
        sa.Column("expected_pace", sa.Float()),
        sa.Column("blowout_probability", sa.Float()),
        sa.Column("game_script", sa.String(40), server_default="neutral"),
        sa.Column("game_script_confidence", sa.Float(), server_default="0"),
        sa.Column("data_quality", sa.String(24), server_default="Thin"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("generated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("actual_home_win", sa.Float()),
        sa.Column("actual_margin", sa.Float()),
        sa.Column("actual_total", sa.Float()),
        sa.Column("actual_home_points", sa.Float()),
        sa.Column("actual_away_points", sa.Float()),
        sa.Column("outcome_source", sa.String(120), server_default=""),
        sa.Column("settled_at", sa.DateTime()),
        sa.UniqueConstraint("prediction_key", name="uq_game_predictions_prediction_key"),
    )
    for column in ("prediction_key", "sport", "game_id", "game_start", "model_version", "game_script", "data_quality", "generated_at"):
        op.create_index(f"ix_game_predictions_{column}", "game_predictions", [column])


def downgrade() -> None:
    op.drop_table("game_predictions")
