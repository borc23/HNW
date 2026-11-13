"""listings: offered_since, removed_at (gone from the source), summary_pending (to write)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("offered_since", sa.Date))
    op.add_column("listings", sa.Column("removed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "listings",
        sa.Column("summary_pending", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_listings_source_listing_id", "listings", ["source", "source_listing_id"])


def downgrade() -> None:
    op.drop_index("ix_listings_source_listing_id", "listings")
    op.drop_column("listings", "summary_pending")
    op.drop_column("listings", "removed_at")
    op.drop_column("listings", "offered_since")
