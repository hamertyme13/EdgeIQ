"""add background job ownership

Revision ID: g82d4f1a6b73
Revises: f7c91d2a4e60
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g82d4f1a6b73"
down_revision: str | Sequence[str] | None = "f7c91d2a4e60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("background_jobs")}
    for name, column in (
        ("owner_id", sa.Column("owner_id", sa.String(), server_default="")),
        ("process_id", sa.Column("process_id", sa.Integer(), server_default="0")),
        ("heartbeat_at", sa.Column("heartbeat_at", sa.String(), server_default="")),
    ):
        if name not in columns:
            op.add_column("background_jobs", column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("background_jobs")}
    for column in ("owner_id", "heartbeat_at"):
        name = f"ix_background_jobs_{column}"
        if name not in indexes:
            op.create_index(name, "background_jobs", [column])


def downgrade() -> None:
    for column in ("heartbeat_at", "owner_id"):
        op.drop_index(f"ix_background_jobs_{column}", table_name="background_jobs")
    for column in ("heartbeat_at", "process_id", "owner_id"):
        op.drop_column("background_jobs", column)
