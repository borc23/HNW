"""Postgres implementations of the `ListingRepository` and `JobLog` ports."""

from collections.abc import Collection
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.adapters.db.models import (
    JobLogRow,
    ListingEnrichmentRow,
    ListingRow,
    PropertyRow,
)
from housing_netherlands.core.models import (
    JobRecord,
    JobStatus,
    KnownListing,
    Listing,
    ListingFilters,
    ListingSummary,
    ListingView,
    UnfinishedJob,
)

_LISTING_FIELDS = (
    "source_listing_id",
    "title",
    "price_eur",
    "area_m2",
    "rooms",
    "bedrooms",
    "postcode",
    "city",
    "neighbourhood",
    "description",
    "image_url",
    "build_year",
    "new_build",
    "interior",
    "offered_since",
)


def _conditions(f: ListingFilters) -> list[ColumnElement[bool]]:
    """SQL for `ListingFilters`; a NULL column never satisfies a comparison, so listings that
    don't state a filtered value drop out, as the model documents."""
    row = ListingRow
    conditions: list[ColumnElement[bool]] = []
    if f.place:
        place = f.place
        conditions.append(
            or_(
                row.city.icontains(place, autoescape=True),
                row.neighbourhood.icontains(place, autoescape=True),
                row.postcode.istartswith(place.replace(" ", ""), autoescape=True),
            )
        )
    if f.max_rent is not None:
        conditions.append(row.price_eur <= f.max_rent)
    if f.min_rooms is not None:
        conditions.append(row.rooms >= f.min_rooms)
    if f.min_area is not None:
        conditions.append(row.area_m2 >= f.min_area)
    if f.new_build:
        conditions.append(row.new_build.is_(True))
    if f.interior is not None:
        conditions.append(row.interior == f.interior.value)
    return conditions


# Newest on the source first; listings without a publication date after, newest imported first.
_NEWEST_FIRST = (
    ListingRow.offered_since.desc().nulls_last(),
    ListingRow.first_seen.desc(),
    ListingRow.id.desc(),
)


def _point(listing: Listing) -> Any:
    if listing.latitude is None or listing.longitude is None:
        return None
    return func.ST_SetSRID(func.ST_MakePoint(listing.longitude, listing.latitude), 4326)


class SqlListingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def upsert_listing(self, listing: Listing, *, raw_blob_key: str) -> int:
        values = {f: getattr(listing, f) for f in _LISTING_FIELDS}
        values["raw_blob_key"] = raw_blob_key
        stmt = (
            insert(ListingRow)
            .values(source=listing.source, url=listing.url, **values)
            .on_conflict_do_update(
                constraint="uq_listings_source_url",
                set_={**values, "last_seen": func.now(), "removed_at": None},
            )
            .returning(ListingRow.id, ListingRow.property_id)
        )
        property_values = {"address_text": listing.address_text, "geom": _point(listing)}

        async with self._sessions.begin() as session:
            listing_id, property_id = (await session.execute(stmt)).one()
            if property_id is None:
                property_id = await session.scalar(
                    insert(PropertyRow).values(**property_values).returning(PropertyRow.id)
                )
                await session.execute(
                    update(ListingRow)
                    .where(ListingRow.id == listing_id)
                    .values(property_id=property_id)
                )
            else:
                await session.execute(
                    update(PropertyRow)
                    .where(PropertyRow.id == property_id)
                    .values(**property_values)
                )
        return listing_id

    async def find_enrichment(
        self, listing_id: int, *, prompt_version: str, content_hash: str
    ) -> ListingSummary | None:
        async with self._sessions() as session:
            output = await session.scalar(
                select(ListingEnrichmentRow.output_json).where(
                    ListingEnrichmentRow.listing_id == listing_id,
                    ListingEnrichmentRow.prompt_version == prompt_version,
                    ListingEnrichmentRow.content_hash == content_hash,
                )
            )
        return ListingSummary.model_validate(output) if output is not None else None

    async def save_enrichment(
        self,
        listing_id: int,
        *,
        prompt_version: str,
        content_hash: str,
        model: str,
        output: ListingSummary,
    ) -> None:
        stmt = (
            insert(ListingEnrichmentRow)
            .values(
                listing_id=listing_id,
                prompt_version=prompt_version,
                content_hash=content_hash,
                model=model,
                output_json=output.model_dump(mode="json"),
            )
            .on_conflict_do_nothing(constraint="uq_enrichments_cache_key")
        )
        async with self._sessions.begin() as session:
            await session.execute(stmt)
            await session.execute(
                update(ListingRow).where(ListingRow.id == listing_id).values(summary_pending=False)
            )

    async def mark_summary_pending(self, listing_id: int) -> None:
        await self._set_summary_pending(listing_id, True)

    async def clear_summary_pending(self, listing_id: int) -> None:
        await self._set_summary_pending(listing_id, False)

    async def _set_summary_pending(self, listing_id: int, pending: bool) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(ListingRow)
                .where(ListingRow.id == listing_id)
                .values(summary_pending=pending)
            )

    async def pending_summaries(self, *, limit: int) -> list[int]:
        stmt = (
            select(ListingRow.id)
            .where(ListingRow.summary_pending, ListingRow.removed_at.is_(None))
            .order_by(*_NEWEST_FIRST)
            .limit(limit)
        )
        async with self._sessions() as session:
            return list((await session.scalars(stmt)).all())

    async def known_listings(self, source: str) -> dict[str, KnownListing]:
        stmt = select(ListingRow.source_listing_id, ListingRow.url, ListingRow.last_seen).where(
            ListingRow.source == source, ListingRow.removed_at.is_(None)
        )
        async with self._sessions() as session:
            return {
                listing_id: KnownListing(url=url, last_fetched=seen)
                for listing_id, url, seen in await session.execute(stmt)
            }

    async def mark_removed(self, source: str, urls: Collection[str]) -> int:
        if not urls:
            return 0
        stmt = (
            update(ListingRow)
            .where(
                ListingRow.source == source,
                ListingRow.url.in_(list(urls)),
                ListingRow.removed_at.is_(None),
            )
            .values(removed_at=func.now())
            .returning(ListingRow.id)
        )
        async with self._sessions.begin() as session:
            return len((await session.scalars(stmt)).all())

    async def list_places(self, *, limit: int = 100) -> list[str]:
        active = ListingRow.removed_at.is_(None)
        names = union_all(
            select(ListingRow.city.label("name")).where(active),
            select(ListingRow.neighbourhood).where(active),
        ).subquery()
        key = func.lower(names.c.name)
        stmt = (
            # One spelling per case-insensitive name; byte order ("C") prefers "Rotterdam"
            # over "rotterdam" whatever the database locale.
            select(func.min(names.c.name.collate("C")))
            .where(names.c.name.is_not(None))
            .group_by(key)
            .order_by(func.count().desc(), key)
            .limit(limit)
        )
        async with self._sessions() as session:
            return list((await session.scalars(stmt)).all())

    async def list_listings(
        self, filters: ListingFilters | None = None, *, limit: int = 50
    ) -> list[ListingView]:
        conditions = [ListingRow.removed_at.is_(None), *_conditions(filters or ListingFilters())]
        return await self._views(conditions, limit=limit)

    async def get_view(self, listing_id: int) -> ListingView | None:
        views = await self._views([ListingRow.id == listing_id], limit=1)
        return views[0] if views else None

    async def _views(
        self, conditions: list[ColumnElement[bool]], *, limit: int
    ) -> list[ListingView]:
        latest = (
            select(ListingEnrichmentRow.listing_id, ListingEnrichmentRow.output_json)
            .ext(distinct_on(ListingEnrichmentRow.listing_id))
            .order_by(ListingEnrichmentRow.listing_id, ListingEnrichmentRow.created_at.desc())
            .subquery()
        )
        stmt = (
            select(
                ListingRow,
                PropertyRow.address_text,
                func.ST_Y(PropertyRow.geom).label("lat"),
                func.ST_X(PropertyRow.geom).label("lng"),
                latest.c.output_json,
            )
            .outerjoin(PropertyRow, PropertyRow.id == ListingRow.property_id)
            .outerjoin(latest, latest.c.listing_id == ListingRow.id)
            .where(*conditions)
            .order_by(*_NEWEST_FIRST)
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).all()
        return [
            ListingView(
                id=row.id,
                listing=Listing(
                    source=row.source,
                    url=row.url,
                    address_text=address_text,
                    latitude=lat,
                    longitude=lng,
                    **{f: getattr(row, f) for f in _LISTING_FIELDS},
                ),
                first_seen=row.first_seen,
                last_seen=row.last_seen,
                summary=ListingSummary.model_validate(output) if output is not None else None,
            )
            for row, address_text, lat, lng, output in rows
        ]


class SqlJobLog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(
        self, job_id: str, *, job_type: str, status: JobStatus, error: str | None = None
    ) -> None:
        values: dict[str, Any] = {"type": job_type, "status": status.value, "error": error}
        if status is JobStatus.RUNNING:
            values["started_at"] = func.now()
        elif status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            values["finished_at"] = func.now()
        stmt = (
            insert(JobLogRow)
            .values(id=job_id, **values)
            .on_conflict_do_update(index_elements=[JobLogRow.id], set_=values)
        )
        async with self._sessions.begin() as session:
            await session.execute(stmt)

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._sessions() as session:
            row = await session.get(JobLogRow, job_id)
        if row is None:
            return None
        return JobRecord(
            job_id=row.id, job_type=row.type, status=JobStatus(row.status), error=row.error
        )

    async def unfinished(self, *, older_than_s: float) -> list[UnfinishedJob]:
        open_states = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
        cutoff = func.now() - func.make_interval(0, 0, 0, 0, 0, 0, older_than_s)
        stmt = (
            select(JobLogRow.id, JobLogRow.type)
            .where(JobLogRow.status.in_(open_states), JobLogRow.created_at < cutoff)
            .order_by(JobLogRow.created_at)
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).all()
        return [UnfinishedJob(job_id=job_id, job_type=job_type) for job_id, job_type in rows]
