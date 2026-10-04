"""Index exact player/stat/platform line-history lookups.

Revision ID: q10a6b9d3e75
Revises: p09b5e7f2d46
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q10a6b9d3e75"
down_revision: str | Sequence[str] | None = "p09b5e7f2d46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("prop_line_history")}
    if "ix_prop_line_history_market" not in existing:
        op.create_index("ix_prop_line_history_market", "prop_line_history", ["player", "stat", "platform"])


def downgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("prop_line_history")}
    if "ix_prop_line_history_market" in existing:
        op.drop_index("ix_prop_line_history_market", table_name="prop_line_history")
