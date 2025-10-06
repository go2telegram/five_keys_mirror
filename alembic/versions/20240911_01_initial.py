"""initial schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision = "20240911_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("asked_notify", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notify_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ref_code", sa.String(length=64), nullable=False),
        sa.Column("ref_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ref_joins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ref_conversions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ref_users", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("last_plan", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("referred_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["referred_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_label", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("plan_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "status", name="uq_subscription_active"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"], unique=False)
    op.create_index("ix_subscriptions_external_id", "subscriptions", ["external_id"], unique=False)

    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_leads_user_id", "leads", ["user_id"], unique=False)
    op.create_index("ix_leads_phone", "leads", ["phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_leads_phone", table_name="leads")
    op.drop_index("ix_leads_user_id", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_subscriptions_external_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_table("products")

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
