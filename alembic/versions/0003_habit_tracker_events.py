"""Add habit tracker events and reminders"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_habit_tracker_events"
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

    reminders_default = sa.text("'[]'")
    reminders_last_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        reminders_default = sa.text("'[]'::jsonb")
        reminders_last_default = sa.text("'{}'::jsonb")

    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "habit_reminders_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "habit_reminders_times",
                json_type,
                nullable=False,
                server_default=reminders_default,
            )
        )
        batch_op.add_column(
            sa.Column(
                "habit_reminders_last_sent",
                json_type,
                nullable=False,
                server_default=reminders_last_default,
            )
        )

    bigint_pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    op.create_table(
        "track_events",
        sa.Column("id", bigint_pk, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_track_events_user", "track_events", ["user_id"], unique=False)
    op.create_index("ix_track_events_kind", "track_events", ["kind"], unique=False)
    op.create_index("ix_track_events_ts", "track_events", ["ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_track_events_ts", table_name="track_events")
    op.drop_index("ix_track_events_kind", table_name="track_events")
    op.drop_index("ix_track_events_user", table_name="track_events")
    op.drop_table("track_events")

    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.drop_column("habit_reminders_last_sent")
        batch_op.drop_column("habit_reminders_times")
        batch_op.drop_column("habit_reminders_enabled")
        batch_op.drop_column("timezone")
