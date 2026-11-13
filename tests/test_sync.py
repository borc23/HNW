from datetime import UTC, datetime, timedelta

from housing_netherlands.core.importing import IMPORT_LISTING_JOB
from housing_netherlands.core.models import IndexEntry, JobStatus
from housing_netherlands.core.sync import SyncDeps, check_job_id, import_job_id, sync_listings
from tests.fakes import (
    FakeJobLog,
    FakeJobQueue,
    FakeListingRepository,
    FakeSourceAdapter,
    make_listing,
)

BASE = "https://www.huurwoningen.nl/huren/rotterdam"
NOW = datetime.now(UTC)


def entry(listing_id: str, modified: datetime | None = NOW) -> IndexEntry:
    return IndexEntry(
        source_listing_id=listing_id, url=f"{BASE}/{listing_id}/x/", last_modified=modified
    )


class FakeIndex:
    name = "huurwoningen"

    def __init__(self, *entries: IndexEntry) -> None:
        self.entries = list(entries)

    async def index(self, city: str) -> list[IndexEntry]:
        assert city == "rotterdam"
        return self.entries


async def stored(repo: FakeListingRepository, *ids: str) -> None:
    for i in ids:
        listing = make_listing(source_listing_id=i, url=f"{BASE}/{i}/x/")
        await repo.upsert_listing(listing, raw_blob_key=i)


def make_deps(index: FakeIndex, repo: FakeListingRepository | None = None) -> SyncDeps:
    return SyncDeps(
        index=index,
        listings=repo or FakeListingRepository(),
        job_log=FakeJobLog(),
        queue=FakeJobQueue(),
        sources=[FakeSourceAdapter("huurwoningen", "huurwoningen.nl")],
        city="rotterdam",
    )


def queued_urls(deps: SyncDeps) -> list[str]:
    return [payload["url"] for _, payload, _ in deps.queue.jobs]  # type: ignore[attr-defined]


async def test_new_listings_are_queued_without_inline_summary() -> None:
    deps = make_deps(FakeIndex(entry("new1"), entry("new2", modified=None)))
    result = await sync_listings(deps)

    assert (result.queued, result.checks_queued) == (2, 0)
    dated = import_job_id("huurwoningen", entry("new1"))
    assert dated == f"sync-huurwoningen-new1-{NOW:%Y%m%dT%H%M%S}"
    assert deps.queue.jobs == [  # type: ignore[attr-defined]
        (IMPORT_LISTING_JOB, {"url": f"{BASE}/new1/x/", "summarize_now": False}, dated),
        (
            IMPORT_LISTING_JOB,
            {"url": f"{BASE}/new2/x/", "summarize_now": False},
            "sync-huurwoningen-new2-undated",
        ),
    ]
    job = await deps.job_log.get(dated)
    assert job is not None and job.status is JobStatus.QUEUED


async def test_only_listings_changed_since_last_fetch_are_reimported() -> None:
    repo = FakeListingRepository()
    await stored(repo, "old", "changed", "undated")  # fake: last fetched "now"
    later, earlier = NOW + timedelta(hours=1), NOW - timedelta(days=1)
    index = FakeIndex(entry("old", earlier), entry("changed", later), entry("undated", None))

    deps = make_deps(index, repo)
    result = await sync_listings(deps)

    assert queued_urls(deps) == [f"{BASE}/changed/x/"]
    assert (result.queued, result.checks_queued) == (1, 0)


async def test_a_queued_version_is_not_queued_again() -> None:
    deps = make_deps(FakeIndex(entry("new1")))
    first = await sync_listings(deps)
    second = await sync_listings(deps)  # e.g. the backfill is still running
    assert (first.queued, second.queued, second.already_queued) == (1, 0, 1)
    assert len(deps.queue.jobs) == 1  # type: ignore[attr-defined]


async def test_listings_missing_from_the_index_get_one_check_a_day() -> None:
    repo = FakeListingRepository()
    await stored(repo, "a", "b", "c")
    deps = make_deps(FakeIndex(entry("a", None), entry("b", None)), repo)

    first = await sync_listings(deps, now=NOW)
    again = await sync_listings(deps, now=NOW)  # 15 min later, same day

    assert (first.checks_queued, again.checks_queued, again.already_queued) == (1, 0, 1)
    assert deps.queue.jobs == [  # type: ignore[attr-defined]
        (
            IMPORT_LISTING_JOB,
            {"url": f"{BASE}/c/x/", "summarize_now": False},
            check_job_id("huurwoningen", "c", NOW),
        )
    ]
    assert len(await repo.known_listings("huurwoningen")) == 3  # nothing hidden by the sync
    tomorrow = await sync_listings(deps, now=NOW + timedelta(days=1))
    assert tomorrow.checks_queued == 1


async def test_a_suspiciously_short_index_checks_nothing() -> None:
    repo = FakeListingRepository()
    await stored(repo, "a", "b", "c", "d")
    for index in (FakeIndex(), FakeIndex(entry("a", None))):  # empty, or 1 of 4
        deps = make_deps(index, repo)
        result = await sync_listings(deps)
        assert (result.checks_queued, result.checks_skipped) == (0, True)
        assert deps.queue.jobs == []  # type: ignore[attr-defined]


async def test_a_removed_listing_that_comes_back_is_imported_again() -> None:
    repo = FakeListingRepository()
    await stored(repo, "a", "b")
    await repo.mark_removed("huurwoningen", {f"{BASE}/b/x/"})
    deps = make_deps(FakeIndex(entry("a", None), entry("b", None)), repo)

    result = await sync_listings(deps)

    assert result.queued == 1 and queued_urls(deps) == [f"{BASE}/b/x/"]
