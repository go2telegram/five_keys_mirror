"""Add quiz results table"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_add_quiz_results"
down_revision = "0002_add_referral_user_fk"
branch_labels = None
depends_on = None


def _json_type(bind) -> sa.types.TypeEngine:
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)

    tags_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        tags_default = sa.text("'{}'::jsonb")

    op.create_table(
        "quiz_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("quiz_name", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("tags", json_type, nullable=False, server_default=tags_default),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_quiz_results_user", "quiz_results", ["user_id"], unique=False)
    op.create_index("ix_quiz_results_quiz", "quiz_results", ["quiz_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_quiz_results_quiz", table_name="quiz_results")
    op.drop_index("ix_quiz_results_user", table_name="quiz_results")
    op.drop_table("quiz_results")
