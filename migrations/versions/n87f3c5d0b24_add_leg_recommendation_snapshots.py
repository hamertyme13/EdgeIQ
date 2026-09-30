"""add immutable per-leg recommendation snapshots

Revision ID: n87f3c5d0b24
Revises: m76e2b4c9a13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n87f3c5d0b24"
down_revision: str | Sequence[str] | None = "m76e2b4c9a13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "leg_recommendation_snapshots" not in inspector.get_table_names():
        op.create_table(
            "leg_recommendation_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("snapshot_id", sa.String(64), nullable=False, unique=True),
            sa.Column("feed_snapshot_id", sa.String(), nullable=False),
            sa.Column("offer_snapshot_id", sa.String(64), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("player", sa.String(), nullable=False),
            sa.Column("sport", sa.String(), nullable=False),
            sa.Column("stat", sa.String(), nullable=False),
            sa.Column("direction", sa.String(), nullable=False),
            sa.Column("line", sa.Float(), nullable=False),
            sa.Column("projection", sa.Float()),
            sa.Column("confidence", sa.Float()),
            sa.Column("feature_as_of", sa.String(), nullable=False, server_default=""),
            sa.Column("evidence", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("leg_recommendation_snapshots")}
    for name, columns in (
        ("ix_leg_recommendation_snapshots_snapshot_id", ["snapshot_id"]),
        ("ix_leg_recommendation_snapshots_feed_snapshot_id", ["feed_snapshot_id"]),
        ("ix_leg_recommendation_snapshots_offer_snapshot_id", ["offer_snapshot_id"]),
    ):
        if name not in indexes:
            op.create_index(name, "leg_recommendation_snapshots", columns)
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("entry_props")}
    if "leg_recommendation_snapshot_id" not in columns:
        op.add_column("entry_props", sa.Column("leg_recommendation_snapshot_id", sa.String(64), nullable=False, server_default=""))
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("entry_props")}
    if "ix_entry_props_leg_recommendation_snapshot_id" not in indexes:
        op.create_index("ix_entry_props_leg_recommendation_snapshot_id", "entry_props", ["leg_recommendation_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_entry_props_leg_recommendation_snapshot_id", table_name="entry_props")
    op.drop_column("entry_props", "leg_recommendation_snapshot_id")
    for name in (
        "ix_leg_recommendation_snapshots_offer_snapshot_id",
        "ix_leg_recommendation_snapshots_feed_snapshot_id",
        "ix_leg_recommendation_snapshots_snapshot_id",
    ):
        op.drop_index(name, table_name="leg_recommendation_snapshots")
    op.drop_table("leg_recommendation_snapshots")
