"""add founding beta platform

Revision ID: h31f8a2b7c04
Revises: g82d4f1a6b73
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h31f8a2b7c04"
down_revision: str | Sequence[str] | None = "g82d4f1a6b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    if "beta_users" not in existing_tables:
        op.create_table(
        "beta_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(24), nullable=False, server_default="BETA_TESTER"),
        sa.Column("is_beta_tester", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("beta_cohort", sa.String(40), nullable=False, server_default="FOUNDING_25"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("onboarding_completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime()),
        sa.UniqueConstraint("email", name="uq_beta_users_email"),
        sa.UniqueConstraint("username", name="uq_beta_users_username"),
        )
    for column in ("email", "username", "role", "is_beta_tester", "beta_cohort", "is_active", "created_at", "last_active_at"):
        _create_index_if_missing("beta_users", f"ix_beta_users_{column}", [column])

    if "beta_sessions" not in existing_tables:
        op.create_table(
        "beta_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("beta_users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime()),
        )
    for column in ("user_id", "token_hash", "started_at", "expires_at", "ended_at"):
        _create_index_if_missing("beta_sessions", f"ix_beta_sessions_{column}", [column])

    product_columns = {column["name"] for column in sa.inspect(bind).get_columns("product_events")}
    product_foreign_keys = {
        foreign_key.get("name") for foreign_key in sa.inspect(bind).get_foreign_keys("product_events")
    }
    product_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("product_events")}
    if (
        "user_id" not in product_columns
        or "session_id" not in product_columns
        or "fk_product_events_user" not in product_foreign_keys
        or "fk_product_events_session" not in product_foreign_keys
        or "ix_product_events_user_id" not in product_indexes
        or "ix_product_events_session_id" not in product_indexes
    ):
        with op.batch_alter_table("product_events") as batch:
            if "user_id" not in product_columns:
                batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            if "session_id" not in product_columns:
                batch.add_column(sa.Column("session_id", sa.String(36), nullable=True))
            if "fk_product_events_user" not in product_foreign_keys:
                batch.create_foreign_key("fk_product_events_user", "beta_users", ["user_id"], ["id"])
            if "fk_product_events_session" not in product_foreign_keys:
                batch.create_foreign_key("fk_product_events_session", "beta_sessions", ["session_id"], ["id"])
            if "ix_product_events_user_id" not in product_indexes:
                batch.create_index("ix_product_events_user_id", ["user_id"])
            if "ix_product_events_session_id" not in product_indexes:
                batch.create_index("ix_product_events_session_id", ["session_id"])

    if "beta_feedback" not in existing_tables:
        op.create_table(
        "beta_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("beta_users.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("beta_sessions.id")),
        sa.Column("prediction_record_id", sa.Integer(), sa.ForeignKey("prediction_records.id")),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("entries.id")),
        sa.Column("entry_prop_id", sa.Integer(), sa.ForeignKey("entry_props.id")),
        sa.Column("useful", sa.Boolean()),
        sa.Column("changed_decision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("initial_pick", sa.String(16), nullable=False, server_default="Unsure"),
        sa.Column("final_pick", sa.String(16), nullable=False, server_default="Pass"),
        sa.Column("would_pick", sa.String(16), nullable=False, server_default="Unsure"),
        sa.Column("would_pay", sa.String(32), nullable=False, server_default=""),
        sa.Column("feedback_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "prediction_record_id", "entry_prop_id", name="uq_beta_feedback_user_context"),
        )
    for column in ("user_id", "session_id", "prediction_record_id", "entry_id", "entry_prop_id", "changed_decision", "created_at"):
        _create_index_if_missing("beta_feedback", f"ix_beta_feedback_{column}", [column])

    if "beta_issues" not in existing_tables:
        op.create_table(
        "beta_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("beta_users.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("beta_sessions.id")),
        sa.Column("prediction_record_id", sa.Integer(), sa.ForeignKey("prediction_records.id")),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("entries.id")),
        sa.Column("entry_prop_id", sa.Integer(), sa.ForeignKey("entry_props.id")),
        sa.Column("issue_type", sa.String(24), nullable=False),
        sa.Column("category", sa.String(80), nullable=False, server_default="Other"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    for column in ("user_id", "session_id", "prediction_record_id", "entry_id", "entry_prop_id", "issue_type", "category", "normalized_key", "status", "created_at"):
        _create_index_if_missing("beta_issues", f"ix_beta_issues_{column}", [column])


def _create_index_if_missing(table: str, name: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def downgrade() -> None:
    op.drop_table("beta_issues")
    op.drop_table("beta_feedback")
    with op.batch_alter_table("product_events") as batch:
        batch.drop_index("ix_product_events_session_id")
        batch.drop_index("ix_product_events_user_id")
        batch.drop_constraint("fk_product_events_session", type_="foreignkey")
        batch.drop_constraint("fk_product_events_user", type_="foreignkey")
        batch.drop_column("session_id")
        batch.drop_column("user_id")
    op.drop_table("beta_sessions")
    op.drop_table("beta_users")
