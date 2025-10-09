"""Add habit tracker and user profiles"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_add_track_events_and_profiles"
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

    op.create_table(
        "track_events",
        sa.Column("id", bigint_pk, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Float(asdecimal=False), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_track_events_user_kind_ts",
        "track_events",
        ["user_id", "kind", "ts"],
        unique=False,
    )
    op.create_index("ix_track_events_ts", "track_events", ["ts"], unique=False)

    plan_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        plan_default = sa.text("'{}'::jsonb")

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_json", json_type, nullable=True, server_default=plan_default),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_index("ix_track_events_ts", table_name="track_events")
    op.drop_index("ix_track_events_user_kind_ts", table_name="track_events")
    op.drop_table("track_events")
