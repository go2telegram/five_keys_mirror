"""link sets for partner urls"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision = "0005_link_sets"
down_revision = "0004_retention_daily_tips"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "link_sets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("registration_url", sa.String(length=512), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("slug", name="uq_link_sets_slug"),
    )

    op.create_table(
        "link_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("link_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(length=128), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("set_id", "product_id", name="uq_link_entries_product"),
    )

    op.create_index("ix_link_entries_set_id", "link_entries", ["set_id"])

    link_sets_table = sa.table(
        "link_sets",
        sa.column("slug", sa.String(length=64)),
        sa.column("title", sa.String(length=128)),
        sa.column("registration_url", sa.String(length=512)),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        link_sets_table,
        [
            {
                "slug": "default",
                "title": "Default",
                "registration_url": None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_link_entries_set_id", table_name="link_entries")
    op.drop_table("link_entries")
    op.drop_table("link_sets")
