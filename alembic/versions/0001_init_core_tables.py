"""init core tables"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init_core_tables"
down_revision = None
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
        "users",
        sa.Column("id", bigint_pk, primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column(
            "created",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("referred_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["referred_by"], ["users.id"]),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_index("ix_users_referred_by", "users", ["referred_by"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("user_id", name="uq_subscriptions_user"),
    )

    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("referrer_id", sa.BigInteger(), nullable=False),
        sa.Column("invited_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "bonus_days",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_index("ix_ref_referrer", "referrals", ["referrer_id"], unique=False)
    op.create_index("ix_ref_invited", "referrals", ["invited_id"], unique=False)
    op.create_index("ix_ref_conv", "referrals", ["converted_at"], unique=False)

    op.create_table(
        "promo_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "code", name="uq_promo_usage"),
    )

    meta_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        meta_default = sa.text("'{}'::jsonb")

    op.create_table(
        "events",
        sa.Column("id", bigint_pk, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("meta", json_type, nullable=False, server_default=meta_default),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_events_user", "events", ["user_id"], unique=False)
    op.create_index("ix_events_name", "events", ["name"], unique=False)
    op.create_index("ix_events_ts", "events", ["ts"], unique=False)

    op.create_table(
        "leads",
        sa.Column("id", bigint_pk, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_leads_ts", "leads", ["ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_leads_ts", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_events_ts", table_name="events")
    op.drop_index("ix_events_name", table_name="events")
    op.drop_index("ix_events_user", table_name="events")
    op.drop_table("events")

    op.drop_table("promo_usage")

    op.drop_index("ix_ref_conv", table_name="referrals")
    op.drop_index("ix_ref_invited", table_name="referrals")
    op.drop_index("ix_ref_referrer", table_name="referrals")
    op.drop_table("referrals")

    op.drop_table("subscriptions")

    op.drop_index("ix_users_referred_by", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
