"""add exact entry offer identity

Revision ID: d94e7f31a205
Revises: b72a19f6c441
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d94e7f31a205"
down_revision: str | Sequence[str] | None = "b72a19f6c441"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("entry_props")}
    with op.batch_alter_table("entry_props") as batch:
        if "provider_event_id" not in columns:
            batch.add_column(sa.Column("provider_event_id", sa.String(), nullable=True, server_default=""))
        if "provider_offer_id" not in columns:
            batch.add_column(sa.Column("provider_offer_id", sa.String(), nullable=True, server_default=""))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("entry_props")}
    if "ix_entry_props_provider_event_id" not in indexes:
        op.create_index("ix_entry_props_provider_event_id", "entry_props", ["provider_event_id"])
    if "ix_entry_props_provider_offer_id" not in indexes:
        op.create_index("ix_entry_props_provider_offer_id", "entry_props", ["provider_offer_id"])


def downgrade() -> None:
    with op.batch_alter_table("entry_props") as batch:
        batch.drop_index("ix_entry_props_provider_offer_id")
        batch.drop_index("ix_entry_props_provider_event_id")
        batch.drop_column("provider_offer_id")
        batch.drop_column("provider_event_id")
