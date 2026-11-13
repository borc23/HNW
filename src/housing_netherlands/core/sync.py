"""Scheduled sync: keep the stored listings of one city in step with a source's index.

New listings and listings changed since we last fetched them are queued as import jobs.
A listing missing from the index is not trusted to be gone (sitemaps leave out some live
listings): its page is re-checked at most once a day, and the import marks it removed only when
the page itself is gone (HTTP 404/410).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from housing_netherlands.core.importing import request_import
from housing_netherlands.core.models import IndexEntry
from housing_netherlands.core.ports import (
    JobLog,
    JobQueue,
    ListingIndex,
    ListingRepository,
    SourceAdapter,
)
from housing_netherlands.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SyncDeps:
    index: ListingIndex
    listings: ListingRepository
    job_log: JobLog
    queue: JobQueue
    sources: Sequence[SourceAdapter]
    city: str
    # If the index lists fewer than this share of the listings we hold, it is treated as a bad
    # read (outage, partial file) and nothing is re-checked.
    min_kept_share: float = 0.5


@dataclass(frozen=True)
class SyncResult:
    queued: int  # imports of new or changed listings
    checks_queued: int  # re-checks of listings missing from the index
    already_queued: int  # an earlier run queued that import or today's check
    checks_skipped: bool  # the index looked incomplete, so nothing was re-checked


def import_job_id(source: str, entry: IndexEntry) -> str:
    """One job per listing version, so overlapping runs never queue the same import twice."""
    version = f"{entry.last_modified:%Y%m%dT%H%M%S}" if entry.last_modified else "undated"
    return f"sync-{source}-{entry.source_listing_id}-{version}"


def check_job_id(source: str, source_listing_id: str, today: datetime) -> str:
    return f"check-{source}-{source_listing_id}-{today:%Y%m%d}"


async def sync_listings(deps: SyncDeps, *, now: datetime | None = None) -> SyncResult:
    source = deps.index.name
    entries = await deps.index.index(deps.city)
    known = await deps.listings.known_listings(source)

    def changed(e: IndexEntry) -> bool:
        stored = known.get(e.source_listing_id)
        if stored is None:
            return True
        return e.last_modified is not None and e.last_modified > stored.last_fetched

    # The index is newest first, so new listings reach the feed first.
    imports = [(import_job_id(source, e), e.url) for e in entries if changed(e)]
    missing = known.keys() - {e.source_listing_id for e in entries}
    skip_checks = len(entries) < deps.min_kept_share * len(known)
    if skip_checks:
        log.warning("sync.checks_skipped", source=source, indexed=len(entries), known=len(known))
    today = now or datetime.now(UTC)
    checks = (
        []
        if skip_checks
        else [(check_job_id(source, i, today), known[i].url) for i in sorted(missing)]
    )

    queued, already_imports = await _queue(deps, imports)
    checks_queued, already_checks = await _queue(deps, checks)
    result = SyncResult(
        queued=queued,
        checks_queued=checks_queued,
        already_queued=already_imports + already_checks,
        checks_skipped=skip_checks,
    )
    log.info("sync.done", source=source, city=deps.city, indexed=len(entries), **vars(result))
    return result


async def _queue(deps: SyncDeps, jobs: list[tuple[str, str]]) -> tuple[int, int]:
    """Queue (job id, url) imports not queued before; return (queued, already queued)."""
    queued = 0
    for job_id, url in jobs:
        if await deps.job_log.get(job_id) is None:
            await request_import(
                deps.queue, deps.job_log, deps.sources, url, job_id=job_id, summarize_now=False
            )
            queued += 1
    return queued, len(jobs) - queued
