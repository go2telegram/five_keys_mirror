"""admin events table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20241005_01"
down_revision = "20240911_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_events_kind", "admin_events", ["kind"], unique=False)
    op.create_index("ix_admin_events_created_at", "admin_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_admin_events_created_at", table_name="admin_events")
    op.drop_index("ix_admin_events_kind", table_name="admin_events")
    op.drop_table("admin_events")
