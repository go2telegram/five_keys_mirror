from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_add_profile_utm_fields"
down_revision = ("0003_add_track_events_and_profiles", "0003_commerce_tables")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("utm_source", sa.String(length=128), nullable=True))
    op.add_column("user_profiles", sa.Column("utm_medium", sa.String(length=128), nullable=True))
    op.add_column("user_profiles", sa.Column("utm_campaign", sa.String(length=128), nullable=True))
    op.add_column("user_profiles", sa.Column("utm_content", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "utm_content")
    op.drop_column("user_profiles", "utm_campaign")
    op.drop_column("user_profiles", "utm_medium")
    op.drop_column("user_profiles", "utm_source")
