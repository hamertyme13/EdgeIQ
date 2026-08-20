"""add persistent research evidence

Revision ID: c73b8e91d442
Revises: a41c3e902211
Create Date: 2026-08-11 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c73b8e91d442"
down_revision: str | Sequence[str] | None = "a41c3e902211"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("player_key", sa.String(), nullable=True),
        sa.Column("player", sa.String(), nullable=True),
        sa.Column("sport", sa.String(), nullable=True),
        sa.Column("stat", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("game_key", sa.String(), nullable=True),
        sa.Column("game", sa.String(), nullable=True),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_kind", sa.String(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loss_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("push_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usefulness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("outcome_keys", sa.Text(), nullable=False, server_default="[]"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id", name="uq_research_evidence_id"),
        sa.UniqueConstraint("fingerprint", name="uq_research_evidence_fingerprint"),
    )
    for column in (
        "evidence_id", "fingerprint", "player_key", "player", "sport", "stat",
        "platform", "game_key", "evidence_type", "source_name", "captured_at", "expires_at",
    ):
        op.create_index(f"ix_research_evidence_{column}", "research_evidence", [column])


def downgrade() -> None:
    op.drop_table("research_evidence")
