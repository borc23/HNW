"""`JobQueue` and the worker runner on Redis via arq. Swaps to SQS later behind QUEUE_BACKEND."""

from collections.abc import MutableMapping
from typing import Any, Self

from arq import Retry, create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.cron import CronJob, cron
from arq.jobs import Job
from arq.jobs import JobStatus as ArqJobStatus
from arq.worker import Function, func

from housing_netherlands.core.errors import DuplicateJobError, RetryLater
from housing_netherlands.core.jobs import JobContext, JobHandler, Lifecycle, Periodic
from housing_netherlands.core.models import QueueJobInfo, QueueJobState
from housing_netherlands.log import bind_context, clear_context


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, redis_url: str) -> Self:
        return cls(await create_pool(RedisSettings.from_dsn(redis_url)))

    async def enqueue(self, job_name: str, payload: dict[str, Any], *, job_id: str) -> None:
        """Queue `job_name(ctx, **payload)`; raise `DuplicateJobError` if `job_id` is still known.

        arq treats `job_id` as a dedup key while the job is queued, running, or its result is
        kept (`keep_result`, 1 h by default), and then returns None instead of a job.
        """
        reserved = [k for k in payload if k.startswith("_")]
        if reserved:
            raise ValueError(f"payload keys must not start with '_': {reserved}")
        if await self._pool.enqueue_job(job_name, _job_id=job_id, **payload) is None:
            raise DuplicateJobError(job_id)

    async def job_info(self, job_id: str) -> QueueJobInfo:
        job = Job(job_id, self._pool)
        status = await job.status()
        if status in (ArqJobStatus.queued, ArqJobStatus.deferred):
            return QueueJobInfo(state=QueueJobState.PENDING)
        if status is ArqJobStatus.in_progress:
            return QueueJobInfo(state=QueueJobState.RUNNING)
        result = await job.result_info() if status is ArqJobStatus.complete else None
        if result is None:  # not found, or the result was already discarded
            return QueueJobInfo(state=QueueJobState.UNKNOWN)
        error = None if result.success else f"{type(result.result).__name__}: {result.result}"
        return QueueJobInfo(state=QueueJobState.DONE, success=result.success, error=error)

    async def close(self) -> None:
        await self._pool.aclose()


def _arq_job(name: str, handler: JobHandler, *, max_tries: int, timeout_s: float) -> Function:
    async def run(ctx: dict[str, Any], **payload: Any) -> Any:
        clear_context()
        bind_context(job_id=ctx["job_id"], job=name, attempt=ctx["job_try"])
        try:
            return await handler(JobContext(ctx["job_id"], ctx["job_try"], ctx), payload)
        except RetryLater as exc:
            raise Retry(defer=exc.delay_s) from exc
        finally:
            clear_context()

    return func(run, name=name, max_tries=max_tries, timeout=timeout_s)


def _arq_cron(name: str, periodic: Periodic) -> CronJob:
    async def run(ctx: dict[str, Any]) -> Any:
        return await periodic.task(ctx)

    every = periodic.every_min
    minutes = None if every == 1 else set(range(0, 60, every))
    # at :00 seconds; unique=True keeps each tick to one run across workers
    return cron(
        run,
        name=name,
        minute=minutes,
        second=0,
        unique=True,
        run_at_startup=True,
        timeout=periodic.timeout_s,
    )


def worker_settings(
    *,
    redis_url: str,
    handlers: dict[str, JobHandler],
    periodic: dict[str, Periodic] | None = None,
    on_startup: Lifecycle,
    on_shutdown: Lifecycle,
    max_tries: int,
    job_timeout_s: float,
) -> type:
    """arq `WorkerSettings` (run with `arq <module>.WorkerSettings`) for queue-independent handlers.

    `max_tries` must exceed the handlers' own attempt limit with headroom: arq also counts runs
    cancelled by a worker restart as tries, and once over `max_tries` it fails the job without
    calling the handler. The handler decides when a job is finished.
    """

    async def startup(ctx: MutableMapping[str, Any]) -> None:
        await on_startup(ctx)

    async def shutdown(ctx: MutableMapping[str, Any]) -> None:
        await on_shutdown(ctx)

    return type(
        "WorkerSettings",
        (),
        {
            "functions": [
                _arq_job(name, h, max_tries=max_tries, timeout_s=job_timeout_s)
                for name, h in handlers.items()
            ],
            "cron_jobs": [_arq_cron(name, t) for name, t in (periodic or {}).items()],
            "redis_settings": RedisSettings.from_dsn(redis_url),
            "on_startup": startup,
            "on_shutdown": shutdown,
            "max_tries": max_tries,
            "job_timeout": job_timeout_s,
        },
    )
