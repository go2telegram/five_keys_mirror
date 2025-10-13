"""Ensure DB indexes and referral uniqueness"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_db_integrity_indexes"
down_revision = "0005_user_profile_utm"
branch_labels = None
depends_on = None


def _get_index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _has_unique_constraint(inspector: sa.Inspector, table: str, columns: list[str]) -> bool:
    target = set(columns)
    for constraint in inspector.get_unique_constraints(table):
        if set(constraint.get("column_names") or []) == target:
            return True
    return False


def _referrer_column(inspector: sa.Inspector) -> str:
    columns = {column["name"] for column in inspector.get_columns("referrals")}
    if "user_id" in columns:
        return "user_id"
    return "referrer_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Ensure username index exists for fast lookups.
    if "ix_users_username" not in _get_index_names(inspector, "users"):
        op.create_index("ix_users_username", "users", ["username"], unique=False)

    # Ensure timestamp index on events for efficient ordering/filtering.
    if "ix_events_ts" not in _get_index_names(inspector, "events"):
        op.create_index("ix_events_ts", "events", ["ts"], unique=False)

    # Ensure referrals are unique per (referrer, invited).
    referrer_col = _referrer_column(inspector)
    columns = [referrer_col, "invited_id"]
    if not _has_unique_constraint(inspector, "referrals", columns):
        constraint_name = (
            "uq_referrals_user_invited"
            if referrer_col == "user_id"
            else "uq_referrals_referrer_invited"
        )
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("referrals", recreate="auto") as batch_op:
                batch_op.create_unique_constraint(constraint_name, columns)
        else:
            op.create_unique_constraint(constraint_name, "referrals", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop referral uniqueness if present.
    referrer_col = _referrer_column(inspector)
    columns = {referrer_col, "invited_id"}
    for constraint in inspector.get_unique_constraints("referrals"):
        if set(constraint.get("column_names") or []) == columns:
            name = constraint["name"]
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("referrals", recreate="auto") as batch_op:
                    batch_op.drop_constraint(name, type_="unique")
            else:
                op.drop_constraint(name, "referrals", type_="unique")
            break

    # Drop events timestamp index if we created it.
    if "ix_events_ts" in _get_index_names(inspector, "events"):
        op.drop_index("ix_events_ts", table_name="events")

    # Drop username index if present.
    if "ix_users_username" in _get_index_names(inspector, "users"):
        op.drop_index("ix_users_username", table_name="users")
