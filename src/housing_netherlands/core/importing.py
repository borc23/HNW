"""Import use-case: listing URL -> raw page archived -> listing stored -> summary (cached).

`request_import` runs in the API (and the scheduled sync): it validates the URL and queues a job.
`run_import_job` runs in the worker: it does the import and keeps `jobs_log` up to date,
deciding whether a failure is worth retrying (`RetryLater`) or final.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from housing_netherlands.core.errors import (
    EnqueueFailedError,
    LLMUnavailableError,
    RetryLater,
    SourceFetchError,
    UnsupportedUrlError,
)
from housing_netherlands.core.models import JobStatus, Listing, LLMParams
from housing_netherlands.core.ports import (
    BlobStore,
    JobLog,
    JobQueue,
    ListingRepository,
    LLMClient,
    SourceAdapter,
)
from housing_netherlands.core.summarize import build_summary_request, summarize
from housing_netherlands.log import get_logger

log = get_logger(__name__)

IMPORT_LISTING_JOB = "import_listing"

_EXTENSIONS = {"text/html": "html", "application/json": "json"}
# The page itself says the listing is gone. Parse errors don't count: a markup change on the
# site must never hide listings.
GONE_STATUSES = frozenset({404, 410})


@dataclass(frozen=True)
class ImportDeps:
    listings: ListingRepository
    job_log: JobLog
    blobs: BlobStore
    llm: LLMClient
    sources: Sequence[SourceAdapter]
    llm_params: LLMParams
    max_attempts: int = 3  # first try + 2 retries
    retry_base_delay_s: float = 30.0  # 30 s, then 60 s


@dataclass(frozen=True)
class ImportResult:
    listing_id: int
    raw_blob_key: str
    summary_cached: bool  # False also when the summary was left to the background task


def find_source(sources: Sequence[SourceAdapter], url: str) -> SourceAdapter:
    for source in sources:
        if source.can_handle(url):
            return source
    raise UnsupportedUrlError(url)


def raw_blob_key(source: str, source_listing_id: str, content_type: str, at: datetime) -> str:
    """e.g. raw/huurwoningen/ea81e68d/20261113T101500Z.html (one object per fetch)."""
    ext = _EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "bin")
    return f"raw/{source}/{source_listing_id}/{at:%Y%m%dT%H%M%SZ}.{ext}"


async def request_import(
    queue: JobQueue,
    job_log: JobLog,
    sources: Sequence[SourceAdapter],
    url: str,
    *,
    job_id: str | None = None,
    summarize_now: bool = True,
) -> str:
    """Validate `url` and queue an import job; return its job id (random unless given).

    `summarize_now=False` leaves a missing summary to the background task (bulk imports), so
    imports don't wait on the LLM.
    Raises `UnsupportedUrlError` (nothing queued) if no enabled source handles the URL, and
    `EnqueueFailedError` (job logged as FAILED, id included) if the queue is unavailable.
    """
    find_source(sources, url)
    job_id = job_id or uuid.uuid4().hex
    # Logged before enqueueing, so the worker's RUNNING can never be overwritten by QUEUED.
    await job_log.record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.QUEUED)
    payload = {"url": url, "summarize_now": summarize_now}
    try:
        await queue.enqueue(IMPORT_LISTING_JOB, payload, job_id=job_id)
    except Exception as exc:
        await job_log.record(
            job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.FAILED, error=f"enqueue: {exc}"
        )
        raise EnqueueFailedError(job_id, f"{type(exc).__name__}: {exc}") from exc
    return job_id


async def import_listing(deps: ImportDeps, url: str, *, summarize_now: bool = True) -> ImportResult:
    """Fetch, archive, store and summarise one listing. Summaries are reused by content hash;
    with `summarize_now=False` a missing one is flagged for the background task instead."""
    source = find_source(deps.sources, url)
    try:
        fetched = await source.fetch(url)
    except SourceFetchError as exc:
        if exc.status in GONE_STATUSES:  # taken down: hide it (a later import brings it back)
            removed = await deps.listings.mark_removed(source.name, [url])
            log.info("listing.gone", url=url, status=exc.status, newly_removed=removed)
        raise
    listing = fetched.listing

    key = raw_blob_key(
        listing.source, listing.source_listing_id, fetched.raw_content_type, datetime.now(UTC)
    )
    await deps.blobs.put(key, fetched.raw, fetched.raw_content_type)
    listing_id = await deps.listings.upsert_listing(listing, raw_blob_key=key)
    cached = await ensure_summary(deps, listing_id, listing, now=summarize_now)
    return ImportResult(listing_id=listing_id, raw_blob_key=key, summary_cached=cached)


async def ensure_summary(deps: ImportDeps, listing_id: int, listing: Listing, *, now: bool) -> bool:
    """Make sure the listing has a summary for its current content; True if one was cached.

    `now=False` flags a missing summary for the background task instead of calling the LLM.
    """
    request = build_summary_request(listing, deps.llm_params)
    cache_key = {"prompt_version": request.prompt_version, "content_hash": request.content_hash}
    if await deps.listings.find_enrichment(listing_id, **cache_key) is not None:
        log.info("enrichment.cache_hit", listing_id=listing_id, **cache_key)
        await deps.listings.clear_summary_pending(listing_id)  # e.g. content changed back
        return True
    if not now:
        await deps.listings.mark_summary_pending(listing_id)
        return False

    result = await summarize(deps.llm, request)
    await deps.listings.save_enrichment(
        listing_id, model=request.params.model, output=result.summary, **cache_key
    )
    log.info("enrichment.saved", listing_id=listing_id, attempts=result.attempts, **cache_key)
    return False


async def run_import_job(
    deps: ImportDeps, *, job_id: str, url: str, attempt: int, summarize_now: bool = True
) -> ImportResult:
    """One attempt of an import job, with `jobs_log` kept in step.

    A temporary failure (fetch: network, bot block, 5xx; LLM: unreachable, timeout, rate limit)
    with attempts left raises `RetryLater` and the job goes back to QUEUED; any other error, or
    the last attempt, is final (FAILED). A retry runs the whole import again (fresh fetch and raw
    snapshot); the listing row is upserted, so nothing is duplicated.
    Cancellation (job timeout, worker shutdown) is recorded as FAILED too, then re-raised; if
    the queue runs the job again, that attempt moves it back to RUNNING. `attempt` counts every
    run, including interrupted ones, so a run past `max_attempts` (the queue allows headroom
    for restarts) still finishes the job: success, or FAILED on any error.
    """
    record = deps.job_log.record
    await record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.RUNNING)
    try:
        result = await import_listing(deps, url, summarize_now=summarize_now)
    except (SourceFetchError, LLMUnavailableError) as exc:
        if exc.retryable and attempt < deps.max_attempts:
            delay = deps.retry_base_delay_s * 2 ** (attempt - 1)
            error = f"attempt {attempt}/{deps.max_attempts} failed, retrying in {delay:g} s: {exc}"
            await record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.QUEUED, error=error)
            raise RetryLater(delay, str(exc)) from exc
        await _record_failed(deps, job_id, exc)
        raise
    except Exception as exc:
        await _record_failed(deps, job_id, exc)
        raise
    except asyncio.CancelledError:
        # BaseException, so not caught above. Shielded: a second cancel (e.g. shutdown after a
        # timeout) must not stop the row from leaving RUNNING.
        await asyncio.shield(
            _record_failed(deps, job_id, "cancelled (job timeout or worker shutdown)")
        )
        raise
    await record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.SUCCEEDED)
    return result


async def _record_failed(deps: ImportDeps, job_id: str, error: Exception | str) -> None:
    if isinstance(error, Exception):
        error = f"{type(error).__name__}: {error}"
    await deps.job_log.record(
        job_id,
        job_type=IMPORT_LISTING_JOB,
        status=JobStatus.FAILED,
        error=error[:2000],
    )
