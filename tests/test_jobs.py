"""reconcile_job_log: finalise jobs_log rows from the queue's own record of each job; and the
scheduling helpers."""

import asyncio
from collections.abc import MutableMapping
from typing import Any

import pytest

from housing_netherlands.core.jobs import Periodic, reconcile_job_log, single_flight
from housing_netherlands.core.models import JobStatus, QueueJobInfo, QueueJobState
from tests.fakes import FakeJobLog, FakeJobQueue

T = "import_listing"


async def _setup(**infos: QueueJobInfo) -> tuple[FakeJobLog, FakeJobQueue]:
    log, queue = FakeJobLog(), FakeJobQueue()
    for job_id, info in infos.items():
        await log.record(job_id, job_type=T, status=JobStatus.RUNNING)
        queue.infos[job_id] = info
    return log, queue


def _last(log: FakeJobLog, job_id: str) -> tuple[str, JobStatus, str | None]:
    return log.records[job_id][-1]


async def test_jobs_still_in_the_queue_are_left_alone() -> None:
    log, queue = await _setup(
        waiting=QueueJobInfo(state=QueueJobState.PENDING),
        busy=QueueJobInfo(state=QueueJobState.RUNNING),
    )
    assert await reconcile_job_log(log, queue) == 0
    assert _last(log, "waiting")[1] is JobStatus.RUNNING
    assert _last(log, "busy")[1] is JobStatus.RUNNING


async def test_job_ended_by_the_queue_is_marked_failed_with_its_error() -> None:
    error = "JobExecutionFailed: max 6 retries exceeded"
    log, queue = await _setup(j=QueueJobInfo(state=QueueJobState.DONE, success=False, error=error))
    assert await reconcile_job_log(log, queue) == 1
    assert _last(log, "j") == (T, JobStatus.FAILED, f"ended by the queue: {error}")


async def test_job_unknown_to_the_queue_is_marked_lost() -> None:
    log, queue = await _setup(j=QueueJobInfo(state=QueueJobState.UNKNOWN))
    await reconcile_job_log(log, queue)
    assert _last(log, "j") == (T, JobStatus.FAILED, "lost: the queue has no record of this job")


async def test_job_that_succeeded_but_missed_its_final_write_is_marked_succeeded() -> None:
    log, queue = await _setup(j=QueueJobInfo(state=QueueJobState.DONE, success=True))
    await reconcile_job_log(log, queue)
    assert _last(log, "j") == (T, JobStatus.SUCCEEDED, None)


async def test_finished_rows_are_not_touched() -> None:
    log, queue = FakeJobLog(), FakeJobQueue()
    await log.record("done", job_type=T, status=JobStatus.SUCCEEDED)
    await log.record("failed", job_type=T, status=JobStatus.FAILED, error="x")
    assert await reconcile_job_log(log, queue) == 0
    assert len(log.records["done"]) == 1 and len(log.records["failed"]) == 1


# --- scheduling ---------------------------------------------------------------------------


async def test_single_flight_skips_a_run_while_the_previous_one_is_going() -> None:
    gate = asyncio.Event()
    runs = []

    async def slow(state: MutableMapping[str, Any]) -> str:
        runs.append(1)
        await gate.wait()
        return "done"

    task = single_flight(slow)
    first = asyncio.ensure_future(task({}))
    await asyncio.sleep(0)
    assert await task({}) is None  # skipped: the first run still holds it
    gate.set()
    assert await first == "done" and len(runs) == 1
    assert await task({}) == "done"  # free again


@pytest.mark.parametrize("every", [0, 61])
def test_periodic_interval_is_validated(every: int) -> None:
    with pytest.raises(ValueError):
        Periodic(single_flight(lambda state: asyncio.sleep(0)), every_min=every)
