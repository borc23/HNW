"""A real arq worker (burst mode) on the test Redis/Postgres/S3, with a fake source and LLM."""

import asyncio
import contextlib
import json
import signal

from arq.jobs import Job, JobStatus
from sqlalchemy import text

from housing_netherlands.adapters.db import SqlJobLog
from housing_netherlands.adapters.queue_arq import ArqJobQueue
from housing_netherlands.config import Settings
from housing_netherlands.core.errors import SourceFetchError, SourceParseError
from housing_netherlands.core.importing import request_import
from housing_netherlands.core.jobs import reconcile_job_log
from housing_netherlands.core.models import FetchedListing, QueueJobState
from housing_netherlands.core.models import JobStatus as LogStatus
from housing_netherlands.wiring import connect_blob_store
from tests.fakes import FakeLLMClient, FakeSourceAdapter, HangingLLM, UnavailableLLM, make_listing
from tests.integration.worker_runner import Sessions, make_worker, run_worker_until_idle

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"
SUMMARY = json.dumps({"summary_en": "Bright flat.", "key_facts": ["EUR 915", "50 m2", "balcony"]})
FETCHED = FetchedListing(
    listing=make_listing(), raw=b"<html>page</html>", raw_content_type="text/html"
)


async def enqueue(settings: Settings, sessions: Sessions, source: FakeSourceAdapter) -> str:
    queue = await ArqJobQueue.connect(settings.redis_url)
    try:
        return await request_import(queue, SqlJobLog(sessions), [source], URL)
    finally:
        await queue.close()


async def job_row(sessions: Sessions, job_id: str) -> tuple[str, str | None]:
    async with sessions() as s:
        query = text("SELECT status, error FROM jobs_log WHERE id = :id")
        row = (await s.execute(query, {"id": job_id})).one()
    return row.status, row.error


async def test_job_imports_listing_end_to_end(settings: Settings, sessions: Sessions) -> None:
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED)
    job_id = await enqueue(settings, sessions, source)
    assert await job_row(sessions, job_id) == ("queued", None)

    await run_worker_until_idle(settings, sessions, source, FakeLLMClient(SUMMARY))

    assert await job_row(sessions, job_id) == ("succeeded", None)
    async with sessions() as s:
        listing = (await s.execute(text("SELECT id, raw_blob_key FROM listings"))).one()
        model = await s.scalar(text("SELECT model FROM listing_enrichments"))
    assert model == "fake-model"

    blobs = await connect_blob_store(settings)
    try:
        assert await blobs.get(listing.raw_blob_key) == FETCHED.raw
    finally:
        await blobs.close()

    queue = await ArqJobQueue.connect(settings.redis_url)
    try:
        info = await Job(job_id, queue._pool).result_info()
    finally:
        await queue.close()
    assert info is not None and info.success
    assert info.result == {"listing_id": listing.id, "summary_cached": False}


async def test_temporary_fetch_error_is_retried_then_succeeds(
    settings: Settings, sessions: Sessions
) -> None:
    source = FakeSourceAdapter(
        "huurwoningen",
        "huurwoningen.nl",
        outcomes=[SourceFetchError("huurwoningen", URL, "HTTP 503", status=503), FETCHED],
    )
    job_id = await enqueue(settings, sessions, source)
    await run_worker_until_idle(settings, sessions, source, FakeLLMClient(SUMMARY))

    assert source.fetched_urls == [URL, URL]  # attempt 1 failed, attempt 2 ran
    assert await job_row(sessions, job_id) == ("succeeded", None)


async def test_permanent_error_fails_job_and_result_keeps_the_error(
    settings: Settings, sessions: Sessions
) -> None:
    error = SourceParseError("huurwoningen", URL, "page has no listing title")
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", outcomes=[error])
    job_id = await enqueue(settings, sessions, source)
    await run_worker_until_idle(settings, sessions, source, FakeLLMClient())

    assert source.fetched_urls == [URL]  # not retried
    assert await job_row(sessions, job_id) == ("failed", f"SourceParseError: {error}")
    queue = await ArqJobQueue.connect(settings.redis_url)
    try:
        job = Job(job_id, queue._pool)
        assert await job.status() == JobStatus.complete
        info = await job.result_info()
    finally:
        await queue.close()
    assert info is not None and not info.success
    assert isinstance(info.result, SourceParseError)  # unpickled with its attributes
    assert info.result.reason == "page has no listing title"


async def test_job_timeout_marks_job_failed_not_running_forever(
    settings: Settings, sessions: Sessions
) -> None:
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED)
    job_id = await enqueue(settings, sessions, source)
    await run_worker_until_idle(settings, sessions, source, HangingLLM(), job_timeout_s=0.5)

    status, error = await job_row(sessions, job_id)
    assert status == "failed"
    assert error is not None and "cancelled" in error
    async with sessions() as s:
        finished = await s.scalar(
            text("SELECT finished_at IS NOT NULL FROM jobs_log WHERE id = :id"), {"id": job_id}
        )
    assert finished


async def test_job_interrupted_by_shutdown_on_its_last_attempt_still_completes(
    settings: Settings, sessions: Sessions
) -> None:
    # Worst case for the attempt budget: the import may only be tried once.
    settings = settings.model_copy(update={"import_max_attempts": 1})
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED)
    job_id = await enqueue(settings, sessions, source)

    hanging = HangingLLM()
    first = make_worker(settings, sessions, source, hanging, burst=False)
    running = asyncio.create_task(first.main())
    await asyncio.wait_for(hanging.started.wait(), 10)
    # Redeploy: arq cancels the job and re-queues it, then the process exits. (handle_sig only
    # stops arq's own main task, which `main()` doesn't use, so stop the poll loop too.)
    first.handle_sig(signal.SIGTERM)
    running.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(running, 10)
    await first.close()
    # The interrupted attempt's FAILED write is shielded but may still be in flight (or cut off
    # by process exit), so don't assert it here; what matters is that the job gets finished.

    await run_worker_until_idle(settings, sessions, source, FakeLLMClient(SUMMARY))

    assert source.fetched_urls == [URL, URL]  # the restarted worker ran the job again
    assert await job_row(sessions, job_id) == ("succeeded", None)


async def backdate_jobs(sessions: Sessions) -> None:
    async with sessions.begin() as s:
        await s.execute(text("UPDATE jobs_log SET created_at = now() - interval '10 minutes'"))


async def test_job_ended_by_arq_without_the_handler_is_reconciled(
    settings: Settings, sessions: Sessions
) -> None:
    # arq fails some jobs without ever calling the handler (here: function not found; same path
    # as expired / aborted before start / max retries exceeded), so jobs_log stays QUEUED.
    job_log = SqlJobLog(sessions)
    queue = await ArqJobQueue.connect(settings.redis_url)
    try:
        await job_log.record("orphan", job_type="no_such_job", status=LogStatus.QUEUED)
        await queue.enqueue("no_such_job", {}, job_id="orphan")
        source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED)
        await run_worker_until_idle(settings, sessions, source, FakeLLMClient())
        assert await job_row(sessions, "orphan") == ("queued", None)  # the gap

        info = await queue.job_info("orphan")
        assert info.state is QueueJobState.DONE and info.success is False

        await backdate_jobs(sessions)
        assert await reconcile_job_log(job_log, queue) == 1
        assert await reconcile_job_log(job_log, queue) == 0  # idempotent
    finally:
        await queue.close()

    status, error = await job_row(sessions, "orphan")
    assert status == "failed"
    assert error == "ended by the queue: JobExecutionFailed: function 'no_such_job' not found"


async def test_reconcile_leaves_finished_and_running_jobs_alone(
    settings: Settings, sessions: Sessions
) -> None:
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED)
    done = await enqueue(settings, sessions, source)
    await run_worker_until_idle(settings, sessions, source, FakeLLMClient(SUMMARY))
    waiting = await enqueue(settings, sessions, source)  # queued, no worker running

    await backdate_jobs(sessions)
    queue = await ArqJobQueue.connect(settings.redis_url)
    try:
        assert await reconcile_job_log(SqlJobLog(sessions), queue) == 0
    finally:
        await queue.close()
    assert (await job_row(sessions, done))[0] == "succeeded"
    assert (await job_row(sessions, waiting))[0] == "queued"


async def test_llm_unavailable_is_retried_by_the_worker(
    settings: Settings, sessions: Sessions
) -> None:
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", FETCHED)
    job_id = await enqueue(settings, sessions, source)
    await run_worker_until_idle(settings, sessions, source, UnavailableLLM(SUMMARY, failures=1))

    assert source.fetched_urls == [URL, URL]  # attempt 2 re-ran the import
    assert await job_row(sessions, job_id) == ("succeeded", None)
    async with sessions() as s:
        # the retry upserted the same listing instead of adding a second one
        assert await s.scalar(text("SELECT count(*) FROM listings")) == 1
        assert await s.scalar(text("SELECT count(*) FROM listing_enrichments")) == 1
