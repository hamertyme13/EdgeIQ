"""add background job ledger

Revision ID: f7c91d2a4e60
Revises: e5b72c4a91f0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c91d2a4e60"
down_revision: str | Sequence[str] | None = "e5b72c4a91f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "background_jobs" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), server_default=""),
        sa.Column("dedupe_key", sa.String(), server_default=""),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("phase", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(), server_default=""),
        sa.Column("started_at", sa.String(), server_default=""),
        sa.Column("completed_at", sa.String(), server_default=""),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false()),
        sa.Column("result_json", sa.Text(), server_default="{}"),
        sa.Column("error", sa.Text(), server_default=""),
        sa.UniqueConstraint("job_id", name="uq_background_jobs_job_id"),
    )
    for column in ("job_id", "kind", "dedupe_key", "status", "created_at"):
        op.create_index(f"ix_background_jobs_{column}", "background_jobs", [column])


def downgrade() -> None:
    op.drop_table("background_jobs")
