from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from housing_netherlands.adapters.blob_s3 import S3BlobStore
from housing_netherlands.adapters.db import (
    SqlJobLog,
    SqlListingRepository,
    create_engine,
    create_session_factory,
)
from housing_netherlands.adapters.queue_arq import ArqJobQueue, worker_settings
from housing_netherlands.adapters.source_huurwoningen import HuurwoningenSource
from housing_netherlands.config import Settings
from housing_netherlands.core.importing import ImportDeps
from housing_netherlands.core.jobs import JobHandler, Lifecycle, Periodic
from housing_netherlands.core.models import LLMParams
from housing_netherlands.core.ports import (
    BlobStore,
    JobLog,
    JobQueue,
    ListingRepository,
    LLMClient,
    SourceAdapter,
)

if TYPE_CHECKING:
    from housing_netherlands.adapters.llm_litellm import LiteLLMClient


@dataclass(frozen=True)
class Adapters:
    listings: ListingRepository
    job_log: JobLog
    blobs: BlobStore
    queue: JobQueue
    llm: LLMClient
    sources: tuple[SourceAdapter, ...]  # only those in SOURCES_ENABLED, in that order


def build_sources(settings: Settings, stack: AsyncExitStack) -> tuple[SourceAdapter, ...]:
    """Create the enabled source adapters; their cleanup is registered on `stack`."""
    sources: list[SourceAdapter] = []
    for name in settings.sources_enabled:
        match name:
            case "huurwoningen":
                source = HuurwoningenSource(
                    timeout_s=settings.huurwoningen_timeout_s,
                    impersonate=settings.huurwoningen_impersonate,
                    min_interval_s=settings.huurwoningen_min_interval_s,
                )
                stack.push_async_callback(source.close)
                sources.append(source)
            case _:
                # Type checkers flag this if a source is added to SourceName without a case.
                assert_never(name)
    return tuple(sources)


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


def build_llm_client(settings: Settings) -> "LiteLLMClient":
    """Stateless (no connections to close); model and params are chosen per call.

    LiteLLM is imported here, not at module level: its import takes ~2 s, so code that only
    imports `wiring` (and the tests) doesn't pay for it.
    """
    from housing_netherlands.adapters.llm_litellm import LiteLLMClient

    return LiteLLMClient(ollama_api_base=settings.ollama_api_base, timeout_s=settings.llm_timeout_s)


def extract_llm_params(settings: Settings) -> LLMParams:
    """Generation params for extraction/summary jobs (part of the LLM cache key)."""
    return LLMParams(
        model=settings.llm_model_extract, reasoning_effort=settings.llm_reasoning_effort
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
            llm=build_llm_client(settings),
            sources=build_sources(settings, stack),
        )


def import_deps(adapters: Adapters, settings: Settings) -> ImportDeps:
    return ImportDeps(
        listings=adapters.listings,
        job_log=adapters.job_log,
        blobs=adapters.blobs,
        llm=adapters.llm,
        sources=adapters.sources,
        llm_params=extract_llm_params(settings),
        max_attempts=settings.import_max_attempts,
        retry_base_delay_s=settings.import_retry_base_delay_s,
    )


# Extra queue-level tries beyond IMPORT_MAX_ATTEMPTS, for runs interrupted by a worker restart
# (arq re-queues a cancelled job and counts it as a try). Without headroom, a restart during
# the last attempt makes arq drop the job without calling the handler. The handler stays the
# one that decides when a job is finished (see run_import_job).
INTERRUPTED_RUN_ALLOWANCE = 3


def build_worker_settings(
    settings: Settings,
    *,
    handlers: dict[str, JobHandler],
    on_startup: Lifecycle,
    on_shutdown: Lifecycle,
    periodic: dict[str, Periodic] | None = None,
) -> type:
    """The queue backend's worker runner for these handlers."""
    # Upper bound for one attempt: fetch + archive + LLM call and its one retry, plus margin.
    job_timeout_s = settings.huurwoningen_timeout_s + 2 * settings.llm_timeout_s + 60
    match settings.queue_backend:
        case "redis":
            return worker_settings(
                redis_url=settings.redis_url,
                handlers=handlers,
                periodic=periodic,
                on_startup=on_startup,
                on_shutdown=on_shutdown,
                max_tries=settings.import_max_attempts + INTERRUPTED_RUN_ALLOWANCE,
                job_timeout_s=job_timeout_s,
            )
        case _:
            assert_never(settings.queue_backend)
