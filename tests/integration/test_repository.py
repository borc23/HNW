from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.adapters.db import SqlJobLog, SqlListingRepository
from housing_netherlands.adapters.db.models import JobLogRow, ListingRow
from housing_netherlands.core import ports
from housing_netherlands.core.models import Interior, JobStatus, ListingFilters, ListingSummary
from tests.fakes import make_listing

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
    listing = make_listing(
        address_text="Zuidplein 1, Rotterdam",
        description="Mooi.",
        neighbourhood="Zuidplein",
        image_url="https://example.org/photo.jpg",
    )
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


async def test_job_log_unfinished_lists_only_old_open_jobs(sessions: Sessions) -> None:
    log = SqlJobLog(sessions)
    for job_id, status in [
        ("old-queued", JobStatus.QUEUED),
        ("old-running", JobStatus.RUNNING),
        ("old-done", JobStatus.SUCCEEDED),
        ("old-failed", JobStatus.FAILED),
        ("new-queued", JobStatus.QUEUED),
    ]:
        await log.record(job_id, job_type="import_listing", status=status)
    async with sessions.begin() as s:
        backdate = (
            "UPDATE jobs_log SET created_at = now() - interval '10 minutes' WHERE id LIKE 'old-%'"
        )
        await s.execute(text(backdate))

    unfinished = await log.unfinished(older_than_s=120)
    assert {(j.job_id, j.job_type) for j in unfinished} == {
        ("old-queued", "import_listing"),
        ("old-running", "import_listing"),
    }
    assert await log.unfinished(older_than_s=3600) == []


# --- search ---------------------------------------------------------------------------------

HOMES = {
    "zuid": dict(
        neighbourhood="Zuidplein",
        postcode="3083CR",
        price_eur=915,
        rooms=3,
        area_m2=50.0,
        new_build=False,
        interior=Interior.BARE,
    ),
    "kop": dict(
        neighbourhood="Kop van Zuid",
        postcode="3072KC",
        price_eur=1900,
        rooms=2,
        area_m2=76.0,
        new_build=True,
        interior=Interior.FURNISHED,
    ),
    "unknown": dict(
        neighbourhood="100%_Centrum",
        postcode="3011ZW",
        price_eur=None,
        rooms=None,
        area_m2=None,
        new_build=None,
        interior=None,
    ),
}


@pytest.fixture
async def homes(repo: SqlListingRepository) -> SqlListingRepository:
    for name, fields in HOMES.items():
        await repo.upsert_listing(
            make_listing(url=f"{BASE}/{name}", title=name, **fields), raw_blob_key=name
        )
    return repo


async def titles(repo: SqlListingRepository, **filters) -> set[str]:
    return {v.listing.title for v in await repo.list_listings(ListingFilters(**filters))}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, {"zuid", "kop", "unknown"}),
        ({"place": "zuid"}, {"zuid", "kop"}),  # neighbourhood, case-insensitive
        ({"place": "rotterdam"}, {"zuid", "kop", "unknown"}),  # city
        ({"place": "3083 c"}, {"zuid"}),  # postcode prefix, spaces ignored
        ({"place": "100%_"}, {"unknown"}),  # wildcards are literal
        ({"place": "Utrecht"}, set()),
        ({"max_rent": 1000}, {"zuid"}),  # unknown rent never matches
        ({"min_rooms": 3}, {"zuid"}),
        ({"min_area": 60}, {"kop"}),
        ({"new_build": True}, {"kop"}),
        ({"new_build": False}, {"zuid", "kop", "unknown"}),  # False doesn't filter
        ({"interior": Interior.BARE}, {"zuid"}),
        ({"place": "zuid", "max_rent": 2000, "new_build": True}, {"kop"}),
    ],
)
async def test_search_filters(homes: SqlListingRepository, filters: dict, expected: set) -> None:
    assert await titles(homes, **filters) == expected


async def test_search_fields_round_trip(homes: SqlListingRepository) -> None:
    [view] = await homes.list_listings(ListingFilters(place="Kop van Zuid"))
    assert (view.listing.new_build, view.listing.interior) == (True, Interior.FURNISHED)


async def test_places_most_listed_first(homes: SqlListingRepository) -> None:
    # Rotterdam is the city of all three homes; ties are alphabetical.
    assert await homes.list_places() == ["Rotterdam", "100%_Centrum", "Kop van Zuid", "Zuidplein"]
    assert await homes.list_places(limit=2) == ["Rotterdam", "100%_Centrum"]


async def test_places_ignore_case(repo: SqlListingRepository) -> None:
    await repo.upsert_listing(make_listing(city="Rotterdam"), raw_blob_key="a")
    await repo.upsert_listing(make_listing(url=f"{BASE}/b", city="rotterdam"), raw_blob_key="b")
    assert await repo.list_places() == ["Rotterdam"]


# --- sync: removal, summary backlog, order --------------------------------------------------


async def test_removed_listings_are_hidden_and_come_back_on_import(
    homes: SqlListingRepository,
) -> None:
    urls = {f"{BASE}/{name}" for name in HOMES}
    known = await homes.known_listings("huurwoningen")
    assert {k.url for k in known.values()} <= urls  # keyed by source id (shared by the fakes)
    assert await homes.mark_removed("huurwoningen", urls) == 3
    assert await homes.mark_removed("huurwoningen", urls) == 0  # already removed
    assert await homes.mark_removed("other-site", urls) == 0
    assert await homes.list_listings() == []
    assert await homes.list_places() == []
    assert await homes.known_listings("huurwoningen") == {}

    await homes.upsert_listing(make_listing(url=f"{BASE}/zuid", title="zuid"), raw_blob_key="z")
    assert [v.listing.title for v in await homes.list_listings()] == ["zuid"]
    view = await homes.get_view(1)
    assert view is not None  # removed listings are still readable by id


async def test_summary_flag_newest_first_and_cleared_by_saving(
    repo: SqlListingRepository,
) -> None:
    old = await repo.upsert_listing(make_listing(url=f"{BASE}/o"), raw_blob_key="o")
    new = await repo.upsert_listing(make_listing(url=f"{BASE}/n"), raw_blob_key="n")
    gone = await repo.upsert_listing(make_listing(url=f"{BASE}/g"), raw_blob_key="g")
    for listing_id in (old, new, gone):
        await repo.mark_summary_pending(listing_id)
    await repo.mark_removed("huurwoningen", {f"{BASE}/o", f"{BASE}/n", f"{BASE}/g"})
    await repo.upsert_listing(make_listing(url=f"{BASE}/o"), raw_blob_key="o")  # back
    await repo.upsert_listing(make_listing(url=f"{BASE}/n"), raw_blob_key="n")  # back

    assert await repo.pending_summaries(limit=5) == [new, old]  # not the removed one
    await repo.save_enrichment(new, prompt_version="v", content_hash="h", model="m", output=SUMMARY)
    await repo.clear_summary_pending(old)
    assert await repo.pending_summaries(limit=5) == []


async def test_feed_is_newest_on_the_source_first(repo: SqlListingRepository) -> None:
    for name, offered in [("a", date(2026, 11, 1)), ("b", None), ("c", date(2026, 11, 12))]:
        listing = make_listing(url=f"{BASE}/{name}", title=name, offered_since=offered)
        await repo.upsert_listing(listing, raw_blob_key=name)
    assert [v.listing.title for v in await repo.list_listings()] == ["c", "a", "b"]
