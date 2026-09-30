"""link complete-board observations to immutable offer snapshots

Revision ID: o98a4d6e1c35
Revises: n87f3c5d0b24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o98a4d6e1c35"
down_revision: str | Sequence[str] | None = "n87f3c5d0b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("board_offer_observations")}
    if "offer_snapshot_id" not in columns:
        op.add_column(
            "board_offer_observations",
            sa.Column("offer_snapshot_id", sa.String(64), nullable=False, server_default=""),
        )
    if "final_game_date" not in columns:
        op.add_column(
            "board_offer_observations",
            sa.Column("final_game_date", sa.String(10), nullable=False, server_default=""),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("board_offer_observations")}
    if "ix_board_offer_observations_offer_snapshot_id" not in indexes:
        op.create_index(
            "ix_board_offer_observations_offer_snapshot_id",
            "board_offer_observations", ["offer_snapshot_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_board_offer_observations_offer_snapshot_id", table_name="board_offer_observations")
    op.drop_column("board_offer_observations", "final_game_date")
    op.drop_column("board_offer_observations", "offer_snapshot_id")
