"""add product experience tables

Revision ID: f92d4a61c830
Revises: e84f9a2c1d10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f92d4a61c830"
down_revision: str | Sequence[str] | None = "e84f9a2c1d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("product_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_name", sa.String(), nullable=False), sa.Column("entity_type", sa.String(), nullable=False, server_default=""), sa.Column("entity_id", sa.String(), nullable=False, server_default=""), sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")))
    for column in ("event_name", "entity_type", "entity_id", "created_at"):
        op.create_index(f"ix_product_events_{column}", "product_events", [column])
    op.create_table("research_sessions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("fingerprint", sa.String(), nullable=False, unique=True), sa.Column("player", sa.String(), nullable=False), sa.Column("sport", sa.String(), nullable=False, server_default=""), sa.Column("stat", sa.String(), nullable=False, server_default=""), sa.Column("platform", sa.String(), nullable=False, server_default=""), sa.Column("line", sa.Float(), nullable=True), sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("run_count", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")))
    for column in ("fingerprint", "player", "sport", "stat", "updated_at"):
        op.create_index(f"ix_research_sessions_{column}", "research_sessions", [column])


def downgrade() -> None:
    op.drop_table("research_sessions")
    op.drop_table("product_events")
