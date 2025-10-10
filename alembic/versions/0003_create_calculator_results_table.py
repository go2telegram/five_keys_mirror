"""create calculator results table"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_create_calculator_results_table"
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

    meta_default = sa.text("'{}'")
    result_default = sa.text("'{}'")
    tags_default = sa.text("'[]'")
    if bind.dialect.name == "postgresql":
        meta_default = sa.text("'{}'::jsonb")
        result_default = sa.text("'{}'::jsonb")
        tags_default = sa.text("'[]'::jsonb")

    op.create_table(
        "calculator_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("calculator", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ok",
        ),
        sa.Column("input_data", json_type, nullable=False, server_default=meta_default),
        sa.Column("result_data", json_type, nullable=False, server_default=result_default),
        sa.Column("tags", json_type, nullable=False, server_default=tags_default),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_calc_results_calc", "calculator_results", ["calculator"], unique=False)
    op.create_index("ix_calc_results_status", "calculator_results", ["status"], unique=False)
    op.create_index("ix_calc_results_created", "calculator_results", ["created"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_calc_results_created", table_name="calculator_results")
    op.drop_index("ix_calc_results_status", table_name="calculator_results")
    op.drop_index("ix_calc_results_calc", table_name="calculator_results")
    op.drop_table("calculator_results")
