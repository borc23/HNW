"""In-memory implementations of the core ports, for unit tests."""

from datetime import UTC, datetime
from typing import Any

from housing_netherlands.core.models import (
    FetchedListing,
    JobStatus,
    Listing,
    ListingSummary,
    ListingView,
    LLMMessage,
    LLMResponse,
)


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any], str]] = []

    async def enqueue(self, job_name: str, payload: dict[str, Any], *, job_id: str) -> None:
        self.jobs.append((job_name, payload, job_id))


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

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(text=self.responses.pop(0), model=model)


class FakeSourceAdapter:
    def __init__(self, name: str, host: str, fetched: FetchedListing | None = None) -> None:
        self.name = name
        self.host = host
        self.fetched = fetched

    def can_handle(self, url: str) -> bool:
        return self.host in url

    async def fetch(self, url: str) -> FetchedListing:
        assert self.fetched is not None, "FakeSourceAdapter has no listing to return"
        return self.fetched


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
