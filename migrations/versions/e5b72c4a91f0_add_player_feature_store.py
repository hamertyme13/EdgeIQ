"""add player feature store

Revision ID: e5b72c4a91f0
Revises: d94e7f31a205
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b72c4a91f0"
down_revision: str | Sequence[str] | None = "d94e7f31a205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "player_features" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "player_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_key", sa.String(), nullable=False),
        sa.Column("player_identity_id", sa.Integer()),
        sa.Column("normalized_player_key", sa.String(), nullable=False),
        sa.Column("player", sa.String(), nullable=False),
        sa.Column("team", sa.String(), server_default=""),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("stat", sa.String(), nullable=False),
        sa.Column("sample_size", sa.Integer(), server_default="0"),
        sa.Column("history_json", sa.Text(), server_default="[]"),
        sa.Column("summary_json", sa.Text(), server_default="{}"),
        sa.Column("source_updated_at", sa.String(), server_default=""),
        sa.Column("materialized_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("feature_key", name="uq_player_features_feature_key"),
        sa.UniqueConstraint("normalized_player_key", "sport", "stat", name="uq_player_feature_segment"),
    )
    for column in ("feature_key", "player_identity_id", "normalized_player_key", "sport", "stat", "materialized_at"):
        op.create_index(f"ix_player_features_{column}", "player_features", [column])


def downgrade() -> None:
    op.drop_table("player_features")
