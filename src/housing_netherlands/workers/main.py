"""Worker process: `arq housing_netherlands.workers.main.WorkerSettings`.

Startup opens all adapters once per process; each job attempt runs `run_import_job`.
Scheduled: job-log reconciliation and background summaries every minute, and the listing
sync every SYNC_EVERY_MIN minutes (off when SYNC_CITY is empty).
"""

from collections.abc import MutableMapping
from contextlib import AsyncExitStack
from typing import Any

from housing_netherlands.config import Settings, get_settings
from housing_netherlands.core.importing import IMPORT_LISTING_JOB, ImportDeps, run_import_job
from housing_netherlands.core.jobs import (
    JobContext,
    JobHandler,
    Periodic,
    reconcile_job_log,
    single_flight,
)
from housing_netherlands.core.ports import ListingIndex
from housing_netherlands.core.summary_backlog import summarize_pending
from housing_netherlands.core.sync import SyncDeps, sync_listings
from housing_netherlands.log import configure_logging, get_logger
from housing_netherlands.wiring import (
    Adapters,
    build_adapters,
    build_worker_settings,
    import_deps,
)

log = get_logger(__name__)


async def startup(state: MutableMapping[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    stack = AsyncExitStack()
    try:
        adapters = await stack.enter_async_context(build_adapters(settings))
    except BaseException:
        await stack.aclose()
        raise
    state["stack"] = stack
    state["adapters"] = adapters
    state["deps"] = import_deps(adapters, settings)
    log.info("worker.started", sources=[s.name for s in adapters.sources])


async def shutdown(state: MutableMapping[str, Any]) -> None:
    stack: AsyncExitStack | None = state.pop("stack", None)
    if stack is not None:
        await stack.aclose()


async def handle_import_listing(job: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    deps: ImportDeps = job.state["deps"]
    result = await run_import_job(
        deps,
        job_id=job.job_id,
        url=payload["url"],
        attempt=job.attempt,
        summarize_now=payload.get("summarize_now", True),  # jobs queued before this field
    )
    log.info("import.done", listing_id=result.listing_id, summary_cached=result.summary_cached)
    return {"listing_id": result.listing_id, "summary_cached": result.summary_cached}


async def reconcile_jobs(state: MutableMapping[str, Any]) -> int:
    adapters: Adapters = state["adapters"]
    return await reconcile_job_log(adapters.job_log, adapters.queue)


async def sync(state: MutableMapping[str, Any]) -> list[str]:
    settings = get_settings()
    adapters: Adapters = state["adapters"]
    assert settings.sync_city  # only scheduled when set
    results = []
    for index in (s for s in adapters.sources if isinstance(s, ListingIndex)):
        deps = SyncDeps(
            index=index,
            listings=adapters.listings,
            job_log=adapters.job_log,
            queue=adapters.queue,
            sources=adapters.sources,
            city=settings.sync_city,
        )
        results.append(repr(await sync_listings(deps)))
    return results


async def summarize_backlog(state: MutableMapping[str, Any]) -> int:
    return await summarize_pending(state["deps"], budget_s=get_settings().summary_batch_s)


def periodic_tasks(settings: Settings) -> dict[str, Periodic]:
    tasks = {
        "reconcile_jobs": Periodic(reconcile_jobs),
        # Room for the last summary started inside the budget (an LLM call and its retry).
        "summarize_backlog": Periodic(
            single_flight(summarize_backlog),
            timeout_s=settings.summary_batch_s + 2 * settings.llm_timeout_s + 30,
        ),
    }
    if settings.sync_city:
        tasks["sync_listings"] = Periodic(single_flight(sync), every_min=settings.sync_every_min)
    return tasks


HANDLERS: dict[str, JobHandler] = {IMPORT_LISTING_JOB: handle_import_listing}

WorkerSettings = build_worker_settings(
    get_settings(),
    handlers=HANDLERS,
    periodic=periodic_tasks(get_settings()),
    on_startup=startup,
    on_shutdown=shutdown,
)
