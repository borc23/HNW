"""Run a real arq worker (burst mode) against the test resources, with any source and LLM."""

from collections.abc import MutableMapping
from contextlib import AsyncExitStack
from typing import Any

from arq.worker import Worker, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.adapters.db import SqlJobLog, SqlListingRepository
from housing_netherlands.config import Settings
from housing_netherlands.core.importing import ImportDeps
from housing_netherlands.core.models import LLMParams
from housing_netherlands.core.ports import LLMClient, SourceAdapter
from housing_netherlands.wiring import build_worker_settings, connect_blob_store
from housing_netherlands.workers.main import HANDLERS

Sessions = async_sessionmaker[AsyncSession]


def make_worker(
    settings: Settings,
    sessions: Sessions,
    source: SourceAdapter,
    llm: LLMClient,
    job_timeout_s: float | None = None,
    *,
    burst: bool = True,
) -> Worker:
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
            max_attempts=settings.import_max_attempts,
            retry_base_delay_s=0.05,
        )

    async def shutdown(state: MutableMapping[str, Any]) -> None:
        await state["stack"].aclose()

    cls = build_worker_settings(
        settings, handlers=HANDLERS, on_startup=startup, on_shutdown=shutdown
    )
    config = {k: v for k, v in vars(cls).items() if not k.startswith("__")}
    if job_timeout_s is not None:  # functions carry their own timeout; rebuild them
        config["functions"] = [
            func(f.coroutine, name=f.name, max_tries=f.max_tries, timeout=job_timeout_s)
            for f in config["functions"]
        ]
    return Worker(**config, burst=burst, poll_delay=0.05, handle_signals=False)


async def run_worker_until_idle(
    settings: Settings,
    sessions: Sessions,
    source: SourceAdapter,
    llm: LLMClient,
    job_timeout_s: float | None = None,
) -> None:
    worker = make_worker(settings, sessions, source, llm, job_timeout_s)
    try:
        await worker.main()  # burst: returns once no job is queued or deferred
    finally:
        await worker.close()
