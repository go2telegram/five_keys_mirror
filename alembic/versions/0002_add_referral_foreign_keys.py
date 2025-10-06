"""Add referral foreign keys and unique constraint.

Revision ID: 0002_add_referral_foreign_keys
Revises: 0001_create_users_and_referrals
Create Date: 2024-09-14 00:05:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_add_referral_foreign_keys"
down_revision = "0001_create_users_and_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM referrals
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC, id DESC) AS rn
                    FROM referrals
                ) t
                WHERE t.rn > 1
            )
            """
        )
    )

    with op.batch_alter_table("referrals") as batch_op:
        batch_op.create_unique_constraint("uq_referrals_user_id", ["user_id"])
        batch_op.create_foreign_key(
            "fk_referrals_referrer_id_users",
            "users",
            ["referrer_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_referrals_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("referrals") as batch_op:
        batch_op.drop_constraint("fk_referrals_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_referrals_referrer_id_users", type_="foreignkey")
        batch_op.drop_constraint("uq_referrals_user_id", type_="unique")
