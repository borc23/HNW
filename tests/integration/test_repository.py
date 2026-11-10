import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.adapters.db import SqlJobLog, SqlListingRepository
from housing_netherlands.adapters.db.models import JobLogRow, ListingRow
from housing_netherlands.core import ports
from housing_netherlands.core.models import JobStatus, ListingSummary
from tests.test_core_models import make_listing

Sessions = async_sessionmaker[AsyncSession]
BASE = "https://www.huurwoningen.nl/huren/rotterdam"
SUMMARY = ListingSummary(summary_en="Bright flat.", key_facts=["50 m2", "EUR 915", "balcony"])


@pytest.fixture
def repo(sessions: Sessions) -> SqlListingRepository:
    return SqlListingRepository(sessions)


def test_adapters_implement_ports(sessions: Sessions) -> None:
    assert isinstance(SqlListingRepository(sessions), ports.ListingRepository)
    assert isinstance(SqlJobLog(sessions), ports.JobLog)


async def test_upsert_creates_listing_with_property_and_point(repo: SqlListingRepository) -> None:
    listing = make_listing(address_text="Zuidplein 1, Rotterdam", description="Mooi.")
    listing_id = await repo.upsert_listing(listing, raw_blob_key="raw/1.json")

    [view] = await repo.list_listings()
    assert view.id == listing_id
    assert view.listing == listing
    assert view.summary is None


async def test_upsert_same_url_updates_in_place(
    repo: SqlListingRepository, sessions: Sessions
) -> None:
    first = await repo.upsert_listing(make_listing(price_eur=915), raw_blob_key="raw/1.json")
    second = await repo.upsert_listing(make_listing(price_eur=950), raw_blob_key="raw/2.json")
    assert first == second

    async with sessions() as s:
        row = await s.scalar(select(ListingRow))
        n_properties = await s.scalar(text("SELECT count(*) FROM properties"))
    assert row is not None
    assert (row.price_eur, row.raw_blob_key) == (950, "raw/2.json")
    assert row.last_seen > row.first_seen
    assert n_properties == 1


async def test_different_urls_are_different_listings(repo: SqlListingRepository) -> None:
    a = await repo.upsert_listing(make_listing(), raw_blob_key="a")
    b = await repo.upsert_listing(make_listing(url=f"{BASE}/b"), raw_blob_key="b")
    assert a != b


async def test_listing_without_coordinates(repo: SqlListingRepository) -> None:
    await repo.upsert_listing(make_listing(latitude=None, longitude=None), raw_blob_key="k")
    [view] = await repo.list_listings()
    assert view.listing.latitude is None and view.listing.longitude is None


async def test_enrichment_cache_hit_and_miss(repo: SqlListingRepository) -> None:
    listing_id = await repo.upsert_listing(make_listing(), raw_blob_key="k")
    key = {"prompt_version": "summary-v1", "content_hash": "abc"}
    assert await repo.find_enrichment(listing_id, **key) is None

    await repo.save_enrichment(listing_id, model="ollama_chat/qwen3.5:4b", output=SUMMARY, **key)
    await repo.save_enrichment(listing_id, model="ollama_chat/qwen3.5:4b", output=SUMMARY, **key)

    assert await repo.find_enrichment(listing_id, **key) == SUMMARY
    other_version = {**key, "prompt_version": "summary-v2"}
    assert await repo.find_enrichment(listing_id, **other_version) is None
    assert (await repo.list_listings())[0].summary == SUMMARY


async def test_list_listings_newest_first_with_limit(repo: SqlListingRepository) -> None:
    for i in range(3):
        await repo.upsert_listing(make_listing(url=f"{BASE}/{i}"), raw_blob_key="k")
    views = await repo.list_listings(limit=2)
    assert [v.listing.url[-1] for v in views] == ["2", "1"]


async def test_job_log_lifecycle(sessions: Sessions) -> None:
    log = SqlJobLog(sessions)
    await log.record("job-1", job_type="import_listing", status=JobStatus.QUEUED)
    await log.record("job-1", job_type="import_listing", status=JobStatus.RUNNING)
    await log.record("job-1", job_type="import_listing", status=JobStatus.FAILED, error="boom")

    async with sessions() as s:
        row = await s.get(JobLogRow, "job-1")
    assert row is not None
    assert (row.status, row.error) == ("failed", "boom")
    assert row.started_at is not None and row.finished_at is not None
    assert row.finished_at >= row.started_at
