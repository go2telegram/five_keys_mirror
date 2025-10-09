"""Add commerce tables for orders, coupons, bundles"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_commerce_tables"
down_revision = "0002_add_referral_user_fk"
branch_labels = None
depends_on = None


_json = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
_json_default = sa.text("'{}'")
_ts_default = sa.text("CURRENT_TIMESTAMP")

def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("items_json", _json, nullable=False, server_default=_json_default),
        sa.Column("amount", sa.Float(asdecimal=False), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("coupon_code", sa.String(length=32), nullable=True),
        sa.Column("utm_json", _json, nullable=False, server_default=_json_default),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_ts_default),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])

    op.create_table(
        "coupons",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount_or_pct", sa.Float(asdecimal=False), nullable=False),
        sa.Column("valid_till", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
    )

    op.create_table(
        "bundles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("items_json", _json, nullable=False, server_default=_json_default),
        sa.Column("price", sa.Float(asdecimal=False), nullable=False),
        sa.Column("active", sa.SmallInteger(), nullable=False, server_default="1"),
    )

    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="active"))
        batch_op.add_column(
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=_ts_default,
            )
        )
        batch_op.add_column(sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("txn_id", sa.String(length=64), nullable=True))

    op.create_table(
        "commerce_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_ts_default),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("txn_id", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Float(asdecimal=False), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_commerce_subscriptions_user_id",
        "commerce_subscriptions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_commerce_subscriptions_user_id", table_name="commerce_subscriptions")
    op.drop_table("commerce_subscriptions")

    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("txn_id")
        batch_op.drop_column("renewed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("status")

    op.drop_table("bundles")
    op.drop_table("coupons")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")
