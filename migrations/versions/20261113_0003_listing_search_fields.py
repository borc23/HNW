"""listings: build year, new build, interior (search filters)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("build_year", sa.Integer))
    op.add_column("listings", sa.Column("new_build", sa.Boolean))
    op.add_column("listings", sa.Column("interior", sa.Text))


def downgrade() -> None:
    op.drop_column("listings", "interior")
    op.drop_column("listings", "new_build")
    op.drop_column("listings", "build_year")
