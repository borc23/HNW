"""SQLAlchemy tables. The schema itself is owned by the Alembic migrations in `migrations/`."""

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PropertyRow(Base):
    """One real home, across all sites (dedupe and BAG matching come later)."""

    __tablename__ = "properties"
    __table_args__ = (Index("ix_properties_geom", "geom", postgresql_using="gist"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bag_id: Mapped[str | None] = mapped_column(Text, unique=True)
    address_text: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[Any] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListingRow(Base):
    """One ad on one source."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "url", name="uq_listings_source_url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("properties.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(Text)
    source_listing_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    price_eur: Mapped[int | None]
    area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2, asdecimal=False))
    rooms: Mapped[int | None]
    bedrooms: Mapped[int | None]
    postcode: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    neighbourhood: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    build_year: Mapped[int | None]
    new_build: Mapped[bool | None]
    interior: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    raw_blob_key: Mapped[str] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListingEnrichmentRow(Base):
    """AI output per listing, keyed by prompt version and content hash (the LLM cache)."""

    __tablename__ = "listing_enrichments"
    __table_args__ = (
        UniqueConstraint(
            "listing_id", "prompt_version", "content_hash", name="uq_enrichments_cache_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    prompt_version: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobLogRow(Base):
    """What ran, for debugging."""

    __tablename__ = "jobs_log"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
