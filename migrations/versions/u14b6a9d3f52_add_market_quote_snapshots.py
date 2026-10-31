"""Capture exact-line research quotes without outcome attribution.

Revision ID: u14b6a9d3f52
Revises: t13f5c8d0e41
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "u14b6a9d3f52"
down_revision: str | Sequence[str] | None = "t13f5c8d0e41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "market_quote_snapshots" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "market_quote_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
            sa.Column("captured_at", sa.String(50), nullable=False),
            sa.Column("player_key", sa.String(200), nullable=False),
            sa.Column("player", sa.String(200), nullable=False),
            sa.Column("platform", sa.String(80), nullable=False),
            sa.Column("provider_offer_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("provider_event_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("game", sa.String(300), nullable=False),
            sa.Column("game_time", sa.String(50), nullable=False),
            sa.Column("line", sa.Float(), nullable=False),
            sa.Column("offer_type", sa.String(40), nullable=False),
            sa.Column("market_event_id", sa.String(160), nullable=False),
            sa.Column("oldest_quote_at", sa.String(50), nullable=False),
            sa.Column("book_count", sa.Integer(), nullable=False),
            sa.Column("market_over_probability", sa.Float(), nullable=False),
            sa.Column("market_under_probability", sa.Float(), nullable=False),
            sa.Column("model_over_probability", sa.Float()),
            sa.Column("model_version", sa.String(160), nullable=False, server_default=""),
            sa.Column("quote_payload", sa.Text(), nullable=False),
        )
    indexes = {row["name"] for row in sa.inspect(bind).get_indexes("market_quote_snapshots")}
    if "ix_market_quote_player_game" not in indexes:
        op.create_index("ix_market_quote_player_game", "market_quote_snapshots", ["player_key", "game_time"])
    if "ix_market_quote_captured_at" not in indexes:
        op.create_index("ix_market_quote_captured_at", "market_quote_snapshots", ["captured_at"])


def downgrade() -> None:
    if "market_quote_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("market_quote_snapshots")
