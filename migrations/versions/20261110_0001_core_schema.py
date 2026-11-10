"""core schema: properties, listings, listing_enrichments, jobs_log

Revision ID: 0001
Revises:
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, *, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=not default,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "properties",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("bag_id", sa.Text, unique=True),
        sa.Column("address_text", sa.Text),
        sa.Column("geom", Geometry("POINT", srid=4326, spatial_index=False)),
        _ts("created_at"),
    )
    op.create_index("ix_properties_geom", "properties", ["geom"], postgresql_using="gist")

    op.create_table(
        "listings",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "property_id", sa.BigInteger, sa.ForeignKey("properties.id", ondelete="SET NULL")
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_listing_id", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("price_eur", sa.Integer),
        sa.Column("area_m2", sa.Numeric(8, 2)),
        sa.Column("rooms", sa.Integer),
        sa.Column("bedrooms", sa.Integer),
        sa.Column("postcode", sa.Text),
        sa.Column("city", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("raw_blob_key", sa.Text, nullable=False),
        _ts("first_seen"),
        _ts("last_seen"),
        sa.UniqueConstraint("source", "url", name="uq_listings_source_url"),
    )
    op.create_index("ix_listings_property_id", "listings", ["property_id"])

    op.create_table(
        "listing_enrichments",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "listing_id",
            sa.BigInteger,
            sa.ForeignKey("listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("output_json", JSONB, nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint(
            "listing_id", "prompt_version", "content_hash", name="uq_enrichments_cache_key"
        ),
    )

    op.create_table(
        "jobs_log",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        _ts("created_at"),
        _ts("started_at", default=False),
        _ts("finished_at", default=False),
    )


def downgrade() -> None:
    op.drop_table("jobs_log")
    op.drop_table("listing_enrichments")
    op.drop_table("listings")
    op.drop_table("properties")
