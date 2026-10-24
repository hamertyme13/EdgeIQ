"""Preserve verified season type for final player stats.

Revision ID: t13f5c8d0e41
Revises: s12e4b7c9d30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "t13f5c8d0e41"
down_revision: str | Sequence[str] | None = "s12e4b7c9d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("final_player_stats")}
    if "season_type" not in columns:
        op.add_column("final_player_stats", sa.Column("season_type", sa.String(), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("final_player_stats")}
    if "season_type" in columns:
        op.drop_column("final_player_stats", "season_type")
