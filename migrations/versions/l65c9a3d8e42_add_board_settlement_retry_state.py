"""add board settlement retry state

Revision ID: l65c9a3d8e42
Revises: k54b8f2c7d31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l65c9a3d8e42"
down_revision: str | Sequence[str] | None = "k54b8f2c7d31"
branch_labels = None
depends_on = None

TABLE = "board_offer_observations"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    additions = {
        "settlement_attempts": sa.Column("settlement_attempts", sa.Integer(), nullable=False, server_default="0"),
        "last_settlement_attempt_at": sa.Column("last_settlement_attempt_at", sa.DateTime(), nullable=True),
        "next_settlement_retry_at": sa.Column("next_settlement_retry_at", sa.DateTime(), nullable=True),
        "settlement_block_reason": sa.Column("settlement_block_reason", sa.Text(), nullable=True, server_default=""),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column(TABLE, column)

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if "ix_board_offer_pending_retry" not in indexes:
        op.create_index(
            "ix_board_offer_pending_retry",
            TABLE,
            ["next_settlement_retry_at"],
            sqlite_where=sa.text("outcome = '' AND next_settlement_retry_at IS NOT NULL"),
        )
    if "ix_board_offer_analyzed" not in indexes:
        op.create_index(
            "ix_board_offer_analyzed",
            TABLE,
            ["analyzed_at"],
            sqlite_where=sa.text("analyzed_at IS NOT NULL"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    for name in (
        "ix_board_offer_analyzed",
        "ix_board_offer_pending_retry",
    ):
        if name in indexes:
            op.drop_index(name, table_name=TABLE)
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(TABLE)}
    for name in (
        "settlement_block_reason",
        "next_settlement_retry_at",
        "last_settlement_attempt_at",
        "settlement_attempts",
    ):
        if name in columns:
            op.drop_column(TABLE, name)
