"""Add UTM field to user profiles."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_user_profile_utm"
down_revision = "0004_retention_daily_tips"
branch_labels = None
depends_on = None


def _json_type(bind) -> sa.types.TypeEngine:
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)
    op.add_column("user_profiles", sa.Column("utm", json_type, nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "utm")
