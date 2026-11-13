"""Import use-case: listing URL -> raw page archived -> listing stored -> summary (cached).

`request_import` runs in the API: it validates the URL and queues a job.
`run_import_job` runs in the worker: it does the import and keeps `jobs_log` up to date,
deciding whether a failure is worth retrying (`RetryLater`) or final.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from housing_netherlands.core.errors import RetryLater, SourceFetchError, UnsupportedUrlError
from housing_netherlands.core.models import JobStatus, LLMParams
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
    summary_cached: bool


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
    queue: JobQueue, job_log: JobLog, sources: Sequence[SourceAdapter], url: str
) -> str:
    """Validate `url` and queue an import job; return its job id.

    Raises `UnsupportedUrlError` (nothing queued) if no enabled source handles the URL.
    """
    find_source(sources, url)
    job_id = uuid.uuid4().hex
    # Logged before enqueueing, so the worker's RUNNING can never be overwritten by QUEUED.
    await job_log.record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.QUEUED)
    try:
        await queue.enqueue(IMPORT_LISTING_JOB, {"url": url}, job_id=job_id)
    except Exception as exc:
        await job_log.record(
            job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.FAILED, error=f"enqueue: {exc}"
        )
        raise
    return job_id


async def import_listing(deps: ImportDeps, url: str) -> ImportResult:
    """Fetch, archive, store and summarise one listing. Summaries are reused by content hash."""
    source = find_source(deps.sources, url)
    fetched = await source.fetch(url)
    listing = fetched.listing

    key = raw_blob_key(
        listing.source, listing.source_listing_id, fetched.raw_content_type, datetime.now(UTC)
    )
    await deps.blobs.put(key, fetched.raw, fetched.raw_content_type)
    listing_id = await deps.listings.upsert_listing(listing, raw_blob_key=key)

    request = build_summary_request(listing, deps.llm_params)
    cache_key = {"prompt_version": request.prompt_version, "content_hash": request.content_hash}
    if await deps.listings.find_enrichment(listing_id, **cache_key) is not None:
        log.info("enrichment.cache_hit", listing_id=listing_id, **cache_key)
        return ImportResult(listing_id=listing_id, raw_blob_key=key, summary_cached=True)

    result = await summarize(deps.llm, request)
    await deps.listings.save_enrichment(
        listing_id, model=request.params.model, output=result.summary, **cache_key
    )
    log.info("enrichment.saved", listing_id=listing_id, attempts=result.attempts, **cache_key)
    return ImportResult(listing_id=listing_id, raw_blob_key=key, summary_cached=False)


async def run_import_job(deps: ImportDeps, *, job_id: str, url: str, attempt: int) -> ImportResult:
    """One attempt of an import job, with `jobs_log` kept in step.

    A retryable fetch failure (network, bot block, 5xx) with attempts left raises `RetryLater`
    and the job goes back to QUEUED; any other error, or the last attempt, is final (FAILED).
    """
    record = deps.job_log.record
    await record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.RUNNING)
    try:
        result = await import_listing(deps, url)
    except SourceFetchError as exc:
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
    await record(job_id, job_type=IMPORT_LISTING_JOB, status=JobStatus.SUCCEEDED)
    return result


async def _record_failed(deps: ImportDeps, job_id: str, exc: Exception) -> None:
    await deps.job_log.record(
        job_id,
        job_type=IMPORT_LISTING_JOB,
        status=JobStatus.FAILED,
        error=f"{type(exc).__name__}: {exc}"[:2000],
    )
