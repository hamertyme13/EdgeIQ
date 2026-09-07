"""add board offer query indexes

Revision ID: k54b8f2c7d31
Revises: j43a7e91c620
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k54b8f2c7d31"
down_revision: str | Sequence[str] | None = "j43a7e91c620"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_board_offer_outcome_captured": ["outcome", "captured_at"],
    "ix_board_offer_sport_captured": ["sport", "captured_at"],
    "ix_board_offer_market_captured": ["market_key", "captured_at"],
    "ix_board_offer_provider_sport_start": ["provider", "sport", "scheduled_start"],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "board_offer_observations" not in inspector.get_table_names():
        return
    existing = {index["name"] for index in inspector.get_indexes("board_offer_observations")}
    for name, columns in INDEXES.items():
        if name not in existing:
            op.create_index(name, "board_offer_observations", columns)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "board_offer_observations" not in inspector.get_table_names():
        return
    existing = {index["name"] for index in inspector.get_indexes("board_offer_observations")}
    for name in reversed(INDEXES):
        if name in existing:
            op.drop_index(name, table_name="board_offer_observations")
