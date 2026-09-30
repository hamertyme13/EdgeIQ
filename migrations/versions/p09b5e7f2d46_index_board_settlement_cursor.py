"""Index complete-board settlement cursor scans.

Revision ID: p09b5e7f2d46
Revises: o98a4d6e1c35
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p09b5e7f2d46"
down_revision: str | Sequence[str] | None = "o98a4d6e1c35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("board_offer_observations")}
    if "ix_board_offer_outcome_id" not in existing:
        op.create_index("ix_board_offer_outcome_id", "board_offer_observations", ["outcome", "id"])


def downgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("board_offer_observations")}
    if "ix_board_offer_outcome_id" in existing:
        op.drop_index("ix_board_offer_outcome_id", table_name="board_offer_observations")
