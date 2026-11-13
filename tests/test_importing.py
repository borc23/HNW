"""Import use-case and job lifecycle, with in-memory fakes for every port."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from housing_netherlands.core.errors import (
    LLMOutputInvalid,
    LLMUnavailableError,
    RetryLater,
    SourceFetchError,
    SourceParseError,
    UnsupportedUrlError,
)
from housing_netherlands.core.importing import (
    IMPORT_LISTING_JOB,
    ImportDeps,
    raw_blob_key,
    request_import,
    run_import_job,
)
from housing_netherlands.core.models import (
    FetchedListing,
    JobStatus,
    LLMParams,
)
from tests.fakes import (
    FakeBlobStore,
    FakeJobLog,
    FakeJobQueue,
    FakeListingRepository,
    FakeLLMClient,
    FakeSourceAdapter,
    HangingLLM,
    UnavailableLLM,
)
from tests.test_core_models import make_listing

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"
SUMMARY = json.dumps({"summary_en": "Bright flat.", "key_facts": ["EUR 915", "50 m2", "balcony"]})
FETCHED = FetchedListing(
    listing=make_listing(), raw=b"<html>page</html>", raw_content_type="text/html; charset=UTF-8"
)
PARAMS = LLMParams(model="ollama_chat/qwen3.5:4b", reasoning_effort="none")


def make_deps(*llm_replies: str, outcomes: list | None = None, **policy: float) -> ImportDeps:
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED, outcomes=outcomes)
    return ImportDeps(
        listings=FakeListingRepository(),
        job_log=FakeJobLog(),
        blobs=FakeBlobStore(),
        llm=FakeLLMClient(*llm_replies),
        sources=[source],
        llm_params=PARAMS,
        **policy,  # type: ignore[arg-type]
    )


def statuses(deps: ImportDeps, job_id: str = "job-1") -> list[JobStatus]:
    return [status for _, status, _ in deps.job_log.records[job_id]]  # type: ignore[attr-defined]


def last_error(deps: ImportDeps, job_id: str = "job-1") -> str | None:
    return deps.job_log.records[job_id][-1][2]  # type: ignore[attr-defined]


# --- request_import (API side) ------------------------------------------------------------


async def test_request_import_logs_queued_then_enqueues() -> None:
    queue, log = FakeJobQueue(), FakeJobLog()
    sources = [FakeSourceAdapter("huurwoningen", "huurwoningen.nl")]
    job_id = await request_import(queue, log, sources, URL)

    assert queue.jobs == [(IMPORT_LISTING_JOB, {"url": URL}, job_id)]
    assert log.records[job_id] == [(IMPORT_LISTING_JOB, JobStatus.QUEUED, None)]


async def test_request_import_gives_unique_job_ids() -> None:
    queue, log = FakeJobQueue(), FakeJobLog()
    sources = [FakeSourceAdapter("huurwoningen", "huurwoningen.nl")]
    ids = {await request_import(queue, log, sources, URL) for _ in range(3)}
    assert len(ids) == 3


async def test_request_import_rejects_unsupported_url_and_queues_nothing() -> None:
    queue, log = FakeJobQueue(), FakeJobLog()
    sources = [FakeSourceAdapter("huurwoningen", "huurwoningen.nl")]
    with pytest.raises(UnsupportedUrlError):
        await request_import(queue, log, sources, "https://www.funda.nl/huur/x")
    assert queue.jobs == [] and log.records == {}


async def test_request_import_marks_failed_if_enqueue_fails() -> None:
    class BrokenQueue(FakeJobQueue):
        async def enqueue(self, job_name: str, payload: dict, *, job_id: str) -> None:
            raise ConnectionError("redis down")

    log = FakeJobLog()
    sources = [FakeSourceAdapter("huurwoningen", "huurwoningen.nl")]
    with pytest.raises(ConnectionError):
        await request_import(BrokenQueue(), log, sources, URL)
    [records] = log.records.values()
    assert [s for _, s, _ in records] == [JobStatus.QUEUED, JobStatus.FAILED]
    assert records[-1][2] == "enqueue: redis down"


# --- run_import_job: happy path and cache ---------------------------------------------------


async def test_import_archives_raw_page_stores_listing_and_summary() -> None:
    deps = make_deps(SUMMARY)
    result = await run_import_job(deps, job_id="job-1", url=URL, attempt=1)

    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.SUCCEEDED]
    assert result.summary_cached is False
    # raw page archived under its own key, with its content type
    data, content_type = deps.blobs.blobs[result.raw_blob_key]  # type: ignore[attr-defined]
    assert (data, content_type) == (FETCHED.raw, FETCHED.raw_content_type)
    assert result.raw_blob_key.startswith("raw/huurwoningen/ea81e68d/")
    assert result.raw_blob_key.endswith(".html")
    # listing stored pointing at that raw page, with the validated summary
    [view] = await deps.listings.list_listings()
    assert view.id == result.listing_id
    assert view.summary is not None and view.summary.key_facts == ["EUR 915", "50 m2", "balcony"]
    stored = deps.listings.listings[(FETCHED.listing.source, FETCHED.listing.url)]  # type: ignore[attr-defined]
    assert stored[2] == result.raw_blob_key


async def test_second_import_of_same_content_makes_no_llm_call() -> None:
    deps = make_deps(SUMMARY)  # only one reply available: a 2nd LLM call would fail
    first = await run_import_job(deps, job_id="job-1", url=URL, attempt=1)
    second = await run_import_job(deps, job_id="job-2", url=URL, attempt=1)

    assert (first.summary_cached, second.summary_cached) == (False, True)
    assert len(deps.llm.calls) == 1  # type: ignore[attr-defined]
    assert first.listing_id == second.listing_id
    assert statuses(deps, "job-2") == [JobStatus.RUNNING, JobStatus.SUCCEEDED]


async def test_changed_listing_text_is_summarised_again() -> None:
    changed = FetchedListing(listing=make_listing(description="Nieuw: met tuin."), raw=b"x")
    deps = make_deps(SUMMARY, SUMMARY, outcomes=[FETCHED, changed])
    await run_import_job(deps, job_id="job-1", url=URL, attempt=1)
    second = await run_import_job(deps, job_id="job-2", url=URL, attempt=1)
    assert second.summary_cached is False
    assert len(deps.llm.calls) == 2  # type: ignore[attr-defined]


# --- run_import_job: failures and retries --------------------------------------------------


async def test_retryable_fetch_error_with_attempts_left_asks_for_retry() -> None:
    deps = make_deps(outcomes=[SourceFetchError("huurwoningen", URL, "HTTP 503", status=503)])
    with pytest.raises(RetryLater) as exc_info:
        await run_import_job(deps, job_id="job-1", url=URL, attempt=1)

    assert exc_info.value.delay_s == 30  # base delay
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.QUEUED]
    assert "attempt 1/3 failed, retrying in 30 s" in (last_error(deps) or "")


async def test_retry_delay_doubles_per_attempt() -> None:
    deps = make_deps(outcomes=[SourceFetchError("huurwoningen", URL, "timeout")])
    with pytest.raises(RetryLater) as exc_info:
        await run_import_job(deps, job_id="job-1", url=URL, attempt=2)
    assert exc_info.value.delay_s == 60


async def test_retryable_error_on_last_attempt_fails_for_good() -> None:
    error = SourceFetchError("huurwoningen", URL, "HTTP 503", status=503)
    deps = make_deps(outcomes=[error])
    with pytest.raises(SourceFetchError):
        await run_import_job(deps, job_id="job-1", url=URL, attempt=3)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]
    assert last_error(deps) == f"SourceFetchError: {error}"


@pytest.mark.parametrize(
    "error",
    [
        SourceFetchError("huurwoningen", URL, "HTTP 404", status=404),  # listing taken down
        SourceParseError("huurwoningen", URL, "page has no listing title"),
    ],
)
async def test_permanent_source_errors_fail_without_retry(error: Exception) -> None:
    deps = make_deps(outcomes=[error])
    with pytest.raises(type(error)):
        await run_import_job(deps, job_id="job-1", url=URL, attempt=1)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]


async def test_invalid_llm_output_fails_but_listing_is_kept() -> None:
    deps = make_deps("nope", "still nope")
    with pytest.raises(LLMOutputInvalid):
        await run_import_job(deps, job_id="job-1", url=URL, attempt=1)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]
    [view] = await deps.listings.list_listings()  # fetched data is not lost
    assert view.summary is None


async def test_unsupported_url_in_worker_fails() -> None:
    deps = make_deps(SUMMARY)
    with pytest.raises(UnsupportedUrlError):
        await run_import_job(deps, job_id="job-1", url="https://example.com/x", attempt=1)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]


async def test_long_error_messages_are_truncated() -> None:
    deps = make_deps(outcomes=[SourceParseError("huurwoningen", URL, "x" * 5000)])
    with pytest.raises(SourceParseError):
        await run_import_job(deps, job_id="job-1", url=URL, attempt=1)
    assert len(last_error(deps) or "") == 2000


# --- raw blob keys --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type,ext",
    [
        ("text/html; charset=UTF-8", "html"),
        ("TEXT/HTML", "html"),
        ("application/json", "json"),
        ("application/octet-stream", "bin"),
    ],
)
def test_raw_blob_key(content_type: str, ext: str) -> None:
    at = datetime(2026, 11, 13, 10, 15, 0, tzinfo=UTC)
    assert raw_blob_key("huurwoningen", "ea81e68d", content_type, at) == (
        f"raw/huurwoningen/ea81e68d/20261113T101500Z.{ext}"
    )


# --- cancellation (job timeout / worker shutdown) ------------------------------------------


async def test_cancelled_job_is_recorded_failed_and_stays_cancelled() -> None:
    llm = HangingLLM()
    deps = ImportDeps(**{**make_deps().__dict__, "llm": llm})
    task = asyncio.create_task(run_import_job(deps, job_id="job-1", url=URL, attempt=1))
    await llm.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]
    assert last_error(deps) == "cancelled (job timeout or worker shutdown)"


async def test_timeout_via_wait_for_is_recorded_failed() -> None:
    # arq runs each job inside asyncio.wait_for(..., job_timeout).
    deps = ImportDeps(**{**make_deps().__dict__, "llm": HangingLLM()})
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(run_import_job(deps, job_id="job-1", url=URL, attempt=1), 0.05)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]


async def test_run_past_max_attempts_still_finishes_the_job() -> None:
    # A restart can make the queue run attempt 4 of 3: the handler must still finalise it.
    error = SourceFetchError("huurwoningen", URL, "HTTP 503", status=503)
    deps = make_deps(outcomes=[error])
    with pytest.raises(SourceFetchError):
        await run_import_job(deps, job_id="job-1", url=URL, attempt=4)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]

    ok = make_deps(SUMMARY)
    await run_import_job(ok, job_id="job-2", url=URL, attempt=4)
    assert statuses(ok, "job-2") == [JobStatus.RUNNING, JobStatus.SUCCEEDED]


# --- LLM temporarily unavailable ------------------------------------------------------------


async def test_llm_unavailable_is_retried_and_listing_is_kept() -> None:
    deps = ImportDeps(**{**make_deps().__dict__, "llm": UnavailableLLM(SUMMARY, failures=1)})
    with pytest.raises(RetryLater) as exc_info:
        await run_import_job(deps, job_id="job-1", url=URL, attempt=1)
    assert exc_info.value.delay_s == 30
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.QUEUED]
    assert "attempt 1/3 failed, retrying" in (last_error(deps) or "")
    [view] = await deps.listings.list_listings()
    assert view.summary is None  # stored, summary pending

    await run_import_job(deps, job_id="job-1", url=URL, attempt=2)  # Ollama is back
    assert statuses(deps)[-1] is JobStatus.SUCCEEDED
    [view] = await deps.listings.list_listings()  # same row, now with its summary
    assert view.summary is not None


async def test_llm_unavailable_on_last_attempt_fails() -> None:
    deps = ImportDeps(**{**make_deps().__dict__, "llm": UnavailableLLM(failures=1)})
    with pytest.raises(LLMUnavailableError):
        await run_import_job(deps, job_id="job-1", url=URL, attempt=3)
    assert statuses(deps) == [JobStatus.RUNNING, JobStatus.FAILED]
