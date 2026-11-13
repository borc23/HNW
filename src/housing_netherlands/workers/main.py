"""Worker process: `arq housing_netherlands.workers.main.WorkerSettings`.

Startup opens all adapters once per process; each job attempt runs `run_import_job`.
"""

from collections.abc import MutableMapping
from contextlib import AsyncExitStack
from typing import Any

from housing_netherlands.config import get_settings
from housing_netherlands.core.importing import IMPORT_LISTING_JOB, ImportDeps, run_import_job
from housing_netherlands.core.jobs import JobContext, JobHandler, PeriodicTask, reconcile_job_log
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
    result = await run_import_job(deps, job_id=job.job_id, url=payload["url"], attempt=job.attempt)
    log.info("import.done", listing_id=result.listing_id, summary_cached=result.summary_cached)
    return {"listing_id": result.listing_id, "summary_cached": result.summary_cached}


async def reconcile_jobs(state: MutableMapping[str, Any]) -> int:
    adapters: Adapters = state["adapters"]
    return await reconcile_job_log(adapters.job_log, adapters.queue)


HANDLERS: dict[str, JobHandler] = {IMPORT_LISTING_JOB: handle_import_listing}
PERIODIC: dict[str, PeriodicTask] = {"reconcile_jobs": reconcile_jobs}

WorkerSettings = build_worker_settings(
    get_settings(),
    handlers=HANDLERS,
    periodic=PERIODIC,
    on_startup=startup,
    on_shutdown=shutdown,
)
