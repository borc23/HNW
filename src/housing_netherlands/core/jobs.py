"""Queue-independent job handler types: the worker runner adapts these to its queue backend."""

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from housing_netherlands.core.models import JobStatus, QueueJobState
from housing_netherlands.core.ports import JobLog, JobQueue
from housing_netherlands.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class JobContext:
    job_id: str
    attempt: int  # 1 for the first try
    state: MutableMapping[str, Any]  # per-process resources set up at worker startup


# A handler raises `RetryLater` to be run again; any other exception fails the job.
JobHandler = Callable[[JobContext, dict[str, Any]], Awaitable[Any]]
Lifecycle = Callable[[MutableMapping[str, Any]], Awaitable[None]]
# Runs once a minute in the worker, with the same per-process state as the handlers.
PeriodicTask = Callable[[MutableMapping[str, Any]], Awaitable[Any]]


# Rows younger than this are left alone: `request_import` logs QUEUED just before enqueueing,
# so for a moment a fresh job is in `jobs_log` but not yet known to the queue.
RECONCILE_MIN_AGE_S = 120.0


async def reconcile_job_log(
    job_log: JobLog, queue: JobQueue, *, min_age_s: float = RECONCILE_MIN_AGE_S
) -> int:
    """Finalise `jobs_log` rows the handler never finished; return how many were updated.

    The queue can end a job without running its handler (expired, aborted before start,
    function not found, max tries exceeded), or a worker can die before its last write.
    The queue's own record of the job is the source of truth for those.
    """
    updated = 0
    for job in await job_log.unfinished(older_than_s=min_age_s):
        info = await queue.job_info(job.job_id)
        if info.state in (QueueJobState.PENDING, QueueJobState.RUNNING):
            continue  # still in the queue's hands
        if info.state is QueueJobState.DONE and info.success:
            status, error = JobStatus.SUCCEEDED, None
        elif info.state is QueueJobState.DONE:
            status, error = JobStatus.FAILED, f"ended by the queue: {info.error}"
        else:
            status, error = JobStatus.FAILED, "lost: the queue has no record of this job"
        await job_log.record(job.job_id, job_type=job.job_type, status=status, error=error)
        log.warning("job_log.reconciled", job_id=job.job_id, status=status.value, error=error)
        updated += 1
    return updated
