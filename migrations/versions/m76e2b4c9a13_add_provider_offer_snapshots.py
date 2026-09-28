"""add stable provider offer snapshots and entry leg links

Revision ID: m76e2b4c9a13
Revises: l65c9a3d8e42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m76e2b4c9a13"
down_revision: str | Sequence[str] | None = "l65c9a3d8e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "provider_offer_snapshots" not in inspector.get_table_names():
        op.create_table(
        "provider_offer_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_offer_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("provider_player_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("provider_event_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("player_key", sa.String(200), nullable=False),
        sa.Column("sport", sa.String(40), nullable=False),
        sa.Column("game", sa.String(300), nullable=False, server_default=""),
        sa.Column("game_start", sa.String(50), nullable=False, server_default=""),
        sa.Column("stat", sa.String(120), nullable=False),
        sa.Column("allowed_directions", sa.Text(), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("offer_type", sa.String(40), nullable=False),
        sa.Column("standard_line", sa.Float()),
        sa.Column("baseline_line", sa.Float()),
        sa.Column("discounted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(120), nullable=False, server_default=""),
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("first_observed_at", sa.String(50), nullable=False, server_default=""),
        sa.Column("last_observed_at", sa.String(50), nullable=False, server_default=""),
        sa.Column("expires_at", sa.String(50), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(50), nullable=False),
        )
    inspector = sa.inspect(op.get_bind())
    offer_indexes = {item["name"] for item in inspector.get_indexes("provider_offer_snapshots")}
    if "ix_provider_offer_snapshot_market" not in offer_indexes:
        op.create_index("ix_provider_offer_snapshot_market", "provider_offer_snapshots", ["sport", "player_key", "stat"])
    if "ix_provider_offer_snapshot_provider_event" not in offer_indexes:
        op.create_index("ix_provider_offer_snapshot_provider_event", "provider_offer_snapshots", ["provider", "provider_event_id"])
    entry_columns = {item["name"] for item in inspector.get_columns("entry_props")}
    if "offer_snapshot_id" not in entry_columns:
        op.add_column("entry_props", sa.Column("offer_snapshot_id", sa.String(64), nullable=False, server_default=""))
    if "recommendation_snapshot_id" not in entry_columns:
        op.add_column("entry_props", sa.Column("recommendation_snapshot_id", sa.String(), nullable=False, server_default=""))
    entry_indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("entry_props")}
    if "ix_entry_props_offer_snapshot_id" not in entry_indexes:
        op.create_index("ix_entry_props_offer_snapshot_id", "entry_props", ["offer_snapshot_id"])
    if "ix_entry_props_recommendation_snapshot_id" not in entry_indexes:
        op.create_index("ix_entry_props_recommendation_snapshot_id", "entry_props", ["recommendation_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_entry_props_recommendation_snapshot_id", table_name="entry_props")
    op.drop_index("ix_entry_props_offer_snapshot_id", table_name="entry_props")
    op.drop_column("entry_props", "recommendation_snapshot_id")
    op.drop_column("entry_props", "offer_snapshot_id")
    op.drop_index("ix_provider_offer_snapshot_provider_event", table_name="provider_offer_snapshots")
    op.drop_index("ix_provider_offer_snapshot_market", table_name="provider_offer_snapshots")
    op.drop_table("provider_offer_snapshots")
