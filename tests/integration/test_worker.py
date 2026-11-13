"""A real arq worker (burst mode) on the test Redis/Postgres/S3, with a fake source and LLM."""

import json
from collections.abc import MutableMapping
from contextlib import AsyncExitStack
from typing import Any

import pytest
from arq.jobs import Job, JobStatus
from arq.worker import Worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.adapters.db import SqlJobLog, SqlListingRepository
from housing_netherlands.adapters.queue_arq import ArqJobQueue
from housing_netherlands.config import Settings
from housing_netherlands.core.errors import SourceFetchError, SourceParseError
from housing_netherlands.core.importing import ImportDeps, request_import
from housing_netherlands.core.models import FetchedListing, LLMParams
from housing_netherlands.wiring import build_worker_settings, connect_blob_store
from housing_netherlands.workers.main import HANDLERS
from tests.fakes import FakeLLMClient, FakeSourceAdapter
from tests.test_core_models import make_listing

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"
SUMMARY = json.dumps({"summary_en": "Bright flat.", "key_facts": ["EUR 915", "50 m2", "balcony"]})
FETCHED = FetchedListing(
    listing=make_listing(), raw=b"<html>page</html>", raw_content_type="text/html"
)

Sessions = async_sessionmaker[AsyncSession]


async def run_worker_until_idle(
    settings: Settings, sessions: Sessions, source: FakeSourceAdapter, llm: FakeLLMClient
) -> None:
    async def startup(state: MutableMapping[str, Any]) -> None:
        stack = AsyncExitStack()
        blobs = await connect_blob_store(settings)
        stack.push_async_callback(blobs.close)
        state["stack"] = stack
        state["deps"] = ImportDeps(
            listings=SqlListingRepository(sessions),
            job_log=SqlJobLog(sessions),
            blobs=blobs,
            llm=llm,
            sources=[source],
            llm_params=LLMParams(model="fake-model"),
            retry_base_delay_s=0.05,
        )

    async def shutdown(state: MutableMapping[str, Any]) -> None:
        await state["stack"].aclose()

    cls = build_worker_settings(
        settings, handlers=HANDLERS, on_startup=startup, on_shutdown=shutdown
    )
    config = {k: v for k, v in vars(cls).items() if not k.startswith("__")}
    worker = Worker(**config, burst=True, poll_delay=0.05, handle_signals=False)
    try:
        await worker.main()  # burst: returns once no job is queued or deferred
    finally:
        await worker.close()


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


@pytest.fixture
def settings(s3_settings: Settings, redis_test_url: str) -> Settings:
    return s3_settings.model_copy(update={"import_max_attempts": 3})


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
