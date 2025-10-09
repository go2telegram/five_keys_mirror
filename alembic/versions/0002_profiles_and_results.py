from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_profiles_and_results"
down_revision = "0001_init_core_tables"
branch_labels = None
depends_on = None


def _json_type(bind) -> sa.types.TypeEngine:
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)
    meta_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        meta_default = sa.text("'{}'::jsonb")

    op.create_table(
        "profiles",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("phone", sa.String(length=512), nullable=True),
        sa.Column("email", sa.String(length=512), nullable=True),
        sa.Column("created", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_profiles_updated", "profiles", ["updated"], unique=False)

    op.create_table(
        "quiz_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("quiz_name", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("result", json_type, server_default=meta_default, nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_quiz_results_created", "quiz_results", ["created"], unique=False)
    op.create_index("ix_quiz_results_user", "quiz_results", ["user_id"], unique=False)

    op.create_table(
        "calculator_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("calculator", sa.String(length=64), nullable=False),
        sa.Column("payload", json_type, server_default=meta_default, nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_calculator_results_created", "calculator_results", ["created"], unique=False)
    op.create_index("ix_calculator_results_user", "calculator_results", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_calculator_results_user", table_name="calculator_results")
    op.drop_index("ix_calculator_results_created", table_name="calculator_results")
    op.drop_table("calculator_results")

    op.drop_index("ix_quiz_results_user", table_name="quiz_results")
    op.drop_index("ix_quiz_results_created", table_name="quiz_results")
    op.drop_table("quiz_results")

    op.drop_index("ix_profiles_updated", table_name="profiles")
    op.drop_table("profiles")
