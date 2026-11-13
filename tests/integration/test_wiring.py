from arq.jobs import Job
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.config import Settings
from housing_netherlands.core import ports
from housing_netherlands.core.models import JobStatus
from housing_netherlands.wiring import build_adapters, connect_blob_store
from tests.fakes import make_listing


async def test_build_adapters_writes_only_to_test_resources(
    s3_settings: Settings,
    redis_test_url: str,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = s3_settings  # == test_settings, with the test bucket ensured
    async with build_adapters(settings) as adapters:
        assert isinstance(adapters.listings, ports.ListingRepository)
        assert isinstance(adapters.job_log, ports.JobLog)
        assert isinstance(adapters.blobs, ports.BlobStore)
        assert isinstance(adapters.queue, ports.JobQueue)

        listing_id = await adapters.listings.upsert_listing(make_listing(), raw_blob_key="k")
        await adapters.job_log.record("wiring-1", job_type="t", status=JobStatus.QUEUED)
        await adapters.blobs.put("test/wiring.txt", b"wired", "text/plain")
        await adapters.queue.enqueue("t", {}, job_id="wiring-1")

    # Postgres: rows are in <db>_test (the `sessions` fixture is bound to it).
    async with sessions() as s:
        assert await s.scalar(text("SELECT current_database()")) == "housing_test"
        assert await s.scalar(text("SELECT id FROM listings")) == listing_id
        assert await s.scalar(text("SELECT status FROM jobs_log WHERE id='wiring-1'")) == "queued"

    # S3: the object is in <bucket>-test.
    store = await connect_blob_store(settings)
    try:
        assert store._bucket == "housing-raw-test"
        assert await store.get("test/wiring.txt") == b"wired"
    finally:
        await store.close()

    # Redis: the job is in db 15.
    redis = Redis.from_url(redis_test_url)
    try:
        assert redis_test_url.endswith("/15")
        assert await Job("wiring-1", redis).info() is not None  # type: ignore[arg-type]
    finally:
        await redis.aclose()
