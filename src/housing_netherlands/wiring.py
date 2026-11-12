from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import assert_never

from housing_netherlands.adapters.blob_s3 import S3BlobStore
from housing_netherlands.adapters.db import (
    SqlJobLog,
    SqlListingRepository,
    create_engine,
    create_session_factory,
)
from housing_netherlands.adapters.queue_arq import ArqJobQueue
from housing_netherlands.config import Settings
from housing_netherlands.core.ports import BlobStore, JobLog, JobQueue, ListingRepository


@dataclass(frozen=True)
class Adapters:
    listings: ListingRepository
    job_log: JobLog
    blobs: BlobStore
    queue: JobQueue


async def connect_blob_store(settings: Settings) -> S3BlobStore:
    """Open a blob store with one long-lived client; the caller must `await store.close()`."""
    return await S3BlobStore.connect(
        bucket=settings.storage_bucket,
        endpoint_url=settings.storage_endpoint,
        region=settings.storage_region,
        access_key=settings.storage_access_key.get_secret_value(),
        secret_key=settings.storage_secret_key.get_secret_value(),
        connect_timeout_s=settings.storage_connect_timeout_s,
        read_timeout_s=settings.storage_read_timeout_s,
        max_attempts=settings.storage_max_attempts,
    )


@asynccontextmanager
async def build_adapters(settings: Settings) -> AsyncIterator[Adapters]:
    """Create all adapters for one process (API or worker) and close them on exit.

    Each resource registers its cleanup as soon as it exists, so a failure part-way through
    startup (e.g. Redis down) still releases what was already opened, and every cleanup runs
    even if an earlier one raises.
    """
    async with AsyncExitStack() as stack:
        engine = create_engine(settings.database_url)
        stack.push_async_callback(engine.dispose)
        sessions = create_session_factory(engine)

        match settings.queue_backend:
            case "redis":
                queue = await ArqJobQueue.connect(settings.redis_url)
                stack.push_async_callback(queue.close)
            case _:
                # Type checkers flag this if a backend is added to the Literal without a case.
                assert_never(settings.queue_backend)

        blobs = await connect_blob_store(settings)
        stack.push_async_callback(blobs.close)

        yield Adapters(
            listings=SqlListingRepository(sessions),
            job_log=SqlJobLog(sessions),
            blobs=blobs,
            queue=queue,
        )
