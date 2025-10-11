"""Add user foreign key to referrals"""

from __future__ import annotations

from alembic import op


def _is_sqlite() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


revision = "0002_add_referral_user_fk"
down_revision = "0001_init_core_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _is_sqlite():
        op.drop_index("ix_ref_referrer", table_name="referrals")
        op.execute("ALTER TABLE referrals RENAME COLUMN referrer_id TO user_id")
        op.create_index("ix_ref_user", "referrals", ["user_id"], unique=False)
        return

    with op.batch_alter_table("referrals", recreate="auto") as batch_op:
        batch_op.drop_index("ix_ref_referrer")
        batch_op.alter_column("referrer_id", new_column_name="user_id")
        batch_op.create_index("ix_ref_user", ["user_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_referrals_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    if _is_sqlite():
        op.drop_index("ix_ref_user", table_name="referrals")
        op.execute("ALTER TABLE referrals RENAME COLUMN user_id TO referrer_id")
        op.create_index("ix_ref_referrer", "referrals", ["referrer_id"], unique=False)
        return

    with op.batch_alter_table("referrals", recreate="auto") as batch_op:
        batch_op.drop_constraint("fk_referrals_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_ref_user")
        batch_op.alter_column("user_id", new_column_name="referrer_id")
        batch_op.create_index("ix_ref_referrer", ["referrer_id"], unique=False)
