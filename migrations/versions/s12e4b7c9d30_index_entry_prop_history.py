"""Index settled player-prop history lookups.

Revision ID: s12e4b7c9d30
Revises: r11c8a4d5e20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s12e4b7c9d30"
down_revision: str | Sequence[str] | None = "r11c8a4d5e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("entry_props")}
    if "ix_entry_props_player_sport_stat" not in existing:
        op.create_index("ix_entry_props_player_sport_stat", "entry_props", ["player_name", "sport", "stat"])


def downgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("entry_props")}
    if "ix_entry_props_player_sport_stat" in existing:
        op.drop_index("ix_entry_props_player_sport_stat", table_name="entry_props")
