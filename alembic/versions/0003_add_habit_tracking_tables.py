"""Add habit tracking and retention tables"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_add_habit_tracking_tables"
down_revision = "0002_add_referral_user_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    op.create_table(
        "retention_pushes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=False),
        sa.Column(
            "last_sent",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("user_id", "flow", name="uq_retention_push"),
    )


def downgrade() -> None:
    op.drop_table("retention_pushes")
    op.drop_index("ix_track_events_ts", table_name="track_events")
    op.drop_index("ix_track_events_user_kind_ts", table_name="track_events")
    op.drop_table("track_events")
