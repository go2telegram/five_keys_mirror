"""add orders table and subscription v2"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0003_add_orders_and_subscription_v2"
down_revision = "0002_add_referral_user_fk"
branch_labels = None
depends_on = None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("product", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("payload_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_orders_user", "orders", ["user_id"], unique=False)
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)
    op.create_unique_constraint("uq_orders_payload", "orders", ["payload_hash"])

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "subscriptions_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("txn_id", sa.String(length=128), nullable=True, unique=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_unique_constraint("uq_subscriptions_user", "subscriptions_v2", ["user_id"])

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    now = datetime.now(timezone.utc)
    if "subscriptions" in inspector.get_table_names():
        rows = list(bind.execute(sa.text("SELECT user_id, plan, since, until FROM subscriptions")))
        insert_stmt = sa.text(
            """
            INSERT INTO subscriptions_v2 (id, user_id, plan, started_at, renewed_at, status, provider)
            VALUES (:id, :user_id, :plan, :started_at, :renewed_at, :status, :provider)
            """
        )
        for row in rows:
            until = _aware(row.until)
            status = "active"
            if until is not None and until <= now:
                status = "expired"
            values = {
                "id": row.user_id,
                "user_id": row.user_id,
                "plan": row.plan or "basic",
                "started_at": _aware(row.since) or now,
                "renewed_at": until,
                "status": status,
                "provider": "legacy",
            }
            bind.execute(insert_stmt, values)
    if "subscriptions" in inspector.get_table_names():
        op.drop_table("subscriptions")
    op.rename_table("subscriptions_v2", "subscriptions")


def downgrade() -> None:  # pragma: no cover - downgrade not required in tests
    op.rename_table("subscriptions", "subscriptions_v2")
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_unique_constraint("uq_subscriptions_user", "subscriptions", ["user_id"])

    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT id, user_id, plan, started_at, renewed_at FROM subscriptions_v2"
            )
        )
    )
    insert_stmt = sa.text(
        """
        INSERT INTO subscriptions (user_id, plan, since, until)
        VALUES (:user_id, :plan, :since, :until)
        """
    )
    for row in rows:
        bind.execute(
            insert_stmt,
            {
                "user_id": row.user_id,
                "plan": row.plan,
                "since": _aware(row.started_at) or datetime.now(timezone.utc),
                "until": _aware(row.renewed_at) or datetime.now(timezone.utc),
            },
        )
    op.drop_table("subscriptions_v2")

    op.drop_table("user_profiles")
    op.drop_constraint("uq_orders_payload", "orders", type_="unique")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_user", table_name="orders")
    op.drop_table("orders")
