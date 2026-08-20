"""add plausibility rejection ledger

Revision ID: e84f9a2c1d10
Revises: c73b8e91d442
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e84f9a2c1d10"
down_revision: str | Sequence[str] | None = "c73b8e91d442"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plausibility_rejections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=False),
        sa.Column("original_provider_payload", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("rejected_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("normalized_value", sa.String(), nullable=False, server_default=""),
        sa.Column("expected_minimum", sa.Float(), nullable=True),
        sa.Column("expected_maximum", sa.Float(), nullable=True),
        sa.Column("sport", sa.String(), nullable=False, server_default=""),
        sa.Column("stat", sa.String(), nullable=False, server_default=""),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_plausibility_rejection_fingerprint"),
    )
    for column in ("fingerprint", "provider", "rejected_at", "last_seen_at", "sport", "stat"):
        op.create_index(f"ix_plausibility_rejections_{column}", "plausibility_rejections", [column])


def downgrade() -> None:
    op.drop_table("plausibility_rejections")
