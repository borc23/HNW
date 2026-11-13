"""Ports: the interfaces core code depends on. Adapters implement them; `wiring` picks which."""

from typing import Any, Protocol, runtime_checkable

from housing_netherlands.core.models import (
    FetchedListing,
    JobStatus,
    Listing,
    ListingSummary,
    ListingView,
    LLMMessage,
    LLMParams,
    LLMResponse,
    QueueJobInfo,
    UnfinishedJob,
)


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(self, job_name: str, payload: dict[str, Any], *, job_id: str) -> None:
        """Queue `job_name` with `payload`.

        `job_id` must be unique per job: it is the correlation id in logs and `jobs_log`, and the
        deduplication key. Raises `DuplicateJobError` if a job with that id is still known to the
        queue (queued, running, or its result retained); the job is then NOT queued again.
        """
        ...

    async def job_info(self, job_id: str) -> QueueJobInfo:
        """What the queue knows about `job_id`, including failures where no handler ran."""
        ...


@runtime_checkable
class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        params: LLMParams,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Return the raw completion text. Callers validate structured output themselves."""
        ...


@runtime_checkable
class SourceAdapter(Protocol):
    name: str

    def can_handle(self, url: str) -> bool: ...

    async def fetch(self, url: str) -> FetchedListing: ...


@runtime_checkable
class ListingRepository(Protocol):
    async def upsert_listing(self, listing: Listing, *, raw_blob_key: str) -> int:
        """Insert or refresh a listing (unique on source + url); return its id."""
        ...

    async def find_enrichment(
        self, listing_id: int, *, prompt_version: str, content_hash: str
    ) -> ListingSummary | None: ...

    async def save_enrichment(
        self,
        listing_id: int,
        *,
        prompt_version: str,
        content_hash: str,
        model: str,
        output: ListingSummary,
    ) -> None: ...

    async def list_listings(self, *, limit: int = 50) -> list[ListingView]: ...


@runtime_checkable
class JobLog(Protocol):
    async def record(
        self, job_id: str, *, job_type: str, status: JobStatus, error: str | None = None
    ) -> None:
        """Create or update the `jobs_log` row for `job_id`."""
        ...

    async def unfinished(self, *, older_than_s: float) -> list[UnfinishedJob]:
        """Jobs still QUEUED or RUNNING whose row was created more than `older_than_s` ago."""
        ...
