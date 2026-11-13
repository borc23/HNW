"""Domain models shared by the API, workers and adapters."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class QueueJobState(StrEnum):
    PENDING = "pending"  # queued or deferred (e.g. waiting for a retry)
    RUNNING = "running"
    DONE = "done"  # finished; see `success` / `error`
    UNKNOWN = "unknown"  # the queue has no record (never queued, expired, result discarded)


class QueueJobInfo(BaseModel):
    """The queue's own view of a job, used to reconcile `jobs_log` with what really happened."""

    state: QueueJobState
    success: bool | None = None
    error: str | None = None


class UnfinishedJob(BaseModel):
    job_id: str
    job_type: str


class JobRecord(BaseModel):
    """A `jobs_log` row as shown to the user."""

    job_id: str
    job_type: str
    status: JobStatus
    error: str | None = None


class Listing(BaseModel):
    """One ad on one source, normalised from whatever the source returns."""

    model_config = ConfigDict(frozen=True)

    source: str
    source_listing_id: str
    url: str
    title: str
    price_eur: int | None = Field(default=None, ge=0)
    area_m2: float | None = Field(default=None, gt=0)
    rooms: int | None = Field(default=None, ge=0)
    bedrooms: int | None = Field(default=None, ge=0)
    address_text: str | None = None
    postcode: str | None = None
    city: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None


class FetchedListing(BaseModel):
    """What a source adapter returns: the parsed listing plus the raw payload to archive."""

    model_config = ConfigDict(frozen=True)

    listing: Listing
    raw: bytes
    raw_content_type: str = "application/json"


class ListingSummary(BaseModel):
    """LLM output for a listing (prompt `summary`); validated before it is stored."""

    model_config = ConfigDict(extra="forbid")  # schema gets additionalProperties: false

    summary_en: str = Field(min_length=1)
    key_facts: list[Annotated[str, Field(min_length=1)]] = Field(min_length=3, max_length=3)


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMParams(BaseModel):
    """Generation settings that change the model's output, so they belong in cache keys.

    Transport details (API base URL, timeouts) are not here: they don't change the output.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    reasoning_effort: str | None = None


class LLMResponse(BaseModel):
    text: str
    model: str


class ListingView(BaseModel):
    """A stored listing with its latest summary, as shown in the API and UI."""

    id: int
    listing: Listing
    first_seen: datetime
    last_seen: datetime
    summary: ListingSummary | None = None
