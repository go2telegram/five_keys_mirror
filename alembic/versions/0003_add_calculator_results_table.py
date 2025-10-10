"""Add calculator results table"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_add_calculator_results_table"
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

    bigint_pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    payload_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        payload_default = sa.text("'{}'::jsonb")

    op.create_table(
        "calculator_results",
        sa.Column("id", bigint_pk, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", json_type, nullable=False, server_default=payload_default),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_calc_results_user", "calculator_results", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_calc_results_user", table_name="calculator_results")
    op.drop_table("calculator_results")
