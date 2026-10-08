"""Index bounded current-season final-stat lookups.

Revision ID: r11c8a4d5e20
Revises: q10a6b9d3e75
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r11c8a4d5e20"
down_revision: str | Sequence[str] | None = "q10a6b9d3e75"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.get_bind().exec_driver_sql("PRAGMA busy_timeout=5000")
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("final_player_stats")}
    if "ix_final_stat_sport_stat_date" not in existing:
        op.create_index("ix_final_stat_sport_stat_date", "final_player_stats", ["sport", "stat", "game_date"])
    if "ix_final_stat_identity_stat_date" not in existing:
        op.create_index("ix_final_stat_identity_stat_date", "final_player_stats", ["player_identity_id", "stat", "game_date"])


def downgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("final_player_stats")}
    if "ix_final_stat_identity_stat_date" in existing:
        op.drop_index("ix_final_stat_identity_stat_date", table_name="final_player_stats")
    if "ix_final_stat_sport_stat_date" in existing:
        op.drop_index("ix_final_stat_sport_stat_date", table_name="final_player_stats")
