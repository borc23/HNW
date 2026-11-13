"""In-memory implementations of the core ports, for unit tests."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from housing_netherlands.core.errors import DuplicateJobError, LLMUnavailableError
from housing_netherlands.core.models import (
    FetchedListing,
    JobRecord,
    JobStatus,
    Listing,
    ListingSummary,
    ListingView,
    LLMMessage,
    LLMParams,
    LLMResponse,
    QueueJobInfo,
    QueueJobState,
    UnfinishedJob,
)


def make_listing(**overrides) -> Listing:
    data = {
        "source": "huurwoningen",
        "source_listing_id": "ea81e68d",
        "url": "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/",
        "title": "Appartement Zuidplein",
        "price_eur": 915,
        "area_m2": 50.0,
        "rooms": 3,
        "postcode": "3083CR",
        "city": "Rotterdam",
        "latitude": 51.88,
        "longitude": 4.49,
    }
    return Listing(**{**data, **overrides})


class FakeJobQueue:
    """Mirrors the port contract: a reused job id raises `DuplicateJobError`."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any], str]] = []
        self.infos: dict[str, QueueJobInfo] = {}

    async def enqueue(self, job_name: str, payload: dict[str, Any], *, job_id: str) -> None:
        if any(existing == job_id for _, _, existing in self.jobs):
            raise DuplicateJobError(job_id)
        self.jobs.append((job_name, payload, job_id))

    async def job_info(self, job_id: str) -> QueueJobInfo:
        """`infos` overrides; otherwise queued jobs are PENDING and others UNKNOWN."""
        if job_id in self.infos:
            return self.infos[job_id]
        queued = any(existing == job_id for _, _, existing in self.jobs)
        return QueueJobInfo(state=QueueJobState.PENDING if queued else QueueJobState.UNKNOWN)


class FakeBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        return self.blobs[key][0]


class FakeLLMClient:
    """Returns queued responses in order and records every call."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[list[LLMMessage]] = []
        self.schemas: list[dict[str, Any] | None] = []
        self.params: list[LLMParams] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        params: LLMParams,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.schemas.append(json_schema)
        self.params.append(params)
        return LLMResponse(text=self.responses.pop(0), model=params.model)


class HangingLLM(FakeLLMClient):
    """An LLM call that never returns (e.g. a slow CPU model) until cancelled; `started` is set
    once the call is in progress."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        params: LLMParams,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class UnavailableLLM(FakeLLMClient):
    """Fails like Ollama restarting, `failures` times, then answers normally."""

    def __init__(self, *replies: str, failures: int) -> None:
        super().__init__(*replies)
        self.failures = failures

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        params: LLMParams,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if self.failures:
            self.failures -= 1
            raise LLMUnavailableError(params.model, "APIConnectionError: connection refused")
        return await super().complete(messages, params=params, json_schema=json_schema)


class FakeSourceAdapter:
    """Returns `fetched` on every call, or plays `outcomes` in order (an exception is raised)."""

    def __init__(
        self,
        name: str,
        host: str,
        fetched: FetchedListing | None = None,
        *,
        outcomes: list[FetchedListing | Exception] | None = None,
    ) -> None:
        self.name = name
        self.host = host
        self.fetched = fetched
        self.outcomes = list(outcomes or [])
        self.fetched_urls: list[str] = []

    def can_handle(self, url: str) -> bool:
        return self.host in url

    async def fetch(self, url: str) -> FetchedListing:
        self.fetched_urls.append(url)
        outcome = self.outcomes.pop(0) if self.outcomes else self.fetched
        if isinstance(outcome, Exception):
            raise outcome
        assert outcome is not None, "FakeSourceAdapter has no listing to return"
        return outcome


class FakeListingRepository:
    def __init__(self) -> None:
        self.listings: dict[tuple[str, str], tuple[int, Listing, str]] = {}
        self.enrichments: dict[tuple[int, str, str], tuple[str, ListingSummary]] = {}

    async def upsert_listing(self, listing: Listing, *, raw_blob_key: str) -> int:
        key = (listing.source, listing.url)
        listing_id = self.listings[key][0] if key in self.listings else len(self.listings) + 1
        self.listings[key] = (listing_id, listing, raw_blob_key)
        return listing_id

    async def find_enrichment(
        self, listing_id: int, *, prompt_version: str, content_hash: str
    ) -> ListingSummary | None:
        hit = self.enrichments.get((listing_id, prompt_version, content_hash))
        return hit[1] if hit else None

    async def save_enrichment(
        self,
        listing_id: int,
        *,
        prompt_version: str,
        content_hash: str,
        model: str,
        output: ListingSummary,
    ) -> None:
        self.enrichments[(listing_id, prompt_version, content_hash)] = (model, output)

    async def list_listings(self, *, limit: int = 50) -> list[ListingView]:
        now = datetime.now(UTC)
        summaries = {lid: out for (lid, _, _), (_, out) in self.enrichments.items()}
        return [
            ListingView(
                id=lid, listing=listing, first_seen=now, last_seen=now, summary=summaries.get(lid)
            )
            for lid, listing, _ in self.listings.values()
        ][:limit]


class FakeJobLog:
    def __init__(self) -> None:
        self.records: dict[str, list[tuple[str, JobStatus, str | None]]] = {}

    async def record(
        self, job_id: str, *, job_type: str, status: JobStatus, error: str | None = None
    ) -> None:
        self.records.setdefault(job_id, []).append((job_type, status, error))

    async def get(self, job_id: str) -> JobRecord | None:
        if job_id not in self.records:
            return None
        job_type, status, error = self.records[job_id][-1]
        return JobRecord(job_id=job_id, job_type=job_type, status=status, error=error)

    async def unfinished(self, *, older_than_s: float) -> list[UnfinishedJob]:
        """Ignores age (the SQL adapter's age filter has its own integration test)."""
        open_states = (JobStatus.QUEUED, JobStatus.RUNNING)
        return [
            UnfinishedJob(job_id=job_id, job_type=records[-1][0])
            for job_id, records in self.records.items()
            if records[-1][1] in open_states
        ]


# --- HTTP doubles for HuurwoningenSource (the real parser runs on a saved page) ---------------

HUURWONINGEN_DETAIL_HTML = (
    Path(__file__).parent / "fixtures" / "huurwoningen" / "detail.html"
).read_bytes()


class FakeSession:
    """Records requests and answers each with the next queued response (or exception)."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, float]] = []
        self.closed = False

    async def get(self, url: str, *, timeout: float) -> Any:  # noqa: ASYNC109  # curl_cffi's API
        self.requests.append((url, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self) -> None:
        self.closed = True


def respond(
    status: int = 200,
    content: bytes = HUURWONINGEN_DETAIL_HTML,
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, content=content, headers=headers or {})
