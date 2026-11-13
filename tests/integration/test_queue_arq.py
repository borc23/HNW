from collections.abc import AsyncIterator

import pytest
from arq.constants import result_key_prefix
from arq.jobs import Job, JobStatus

from housing_netherlands.adapters.queue_arq import ArqJobQueue
from housing_netherlands.core import ports
from housing_netherlands.core.errors import DuplicateJobError
from housing_netherlands.core.models import QueueJobState


@pytest.fixture
async def queue(redis_test_url: str) -> AsyncIterator[ArqJobQueue]:
    q = await ArqJobQueue.connect(redis_test_url)
    yield q
    await q.close()


def test_implements_port(queue: ArqJobQueue) -> None:
    assert isinstance(queue, ports.JobQueue)


async def test_enqueue_stores_job_with_payload(queue: ArqJobQueue) -> None:
    url = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"
    await queue.enqueue("import_listing", {"url": url}, job_id="job-1")

    job = Job("job-1", queue._pool)
    assert await job.status() == JobStatus.queued
    info = await job.info()
    assert info is not None
    assert info.function == "import_listing"
    assert info.kwargs == {"url": url}


async def test_reused_job_id_raises_and_is_not_queued(queue: ArqJobQueue) -> None:
    await queue.enqueue("import_listing", {"url": "a"}, job_id="job-1")
    with pytest.raises(DuplicateJobError) as exc_info:
        await queue.enqueue("import_listing", {"url": "b"}, job_id="job-1")

    assert exc_info.value.job_id == "job-1"
    assert len(await queue._pool.queued_jobs()) == 1
    info = await Job("job-1", queue._pool).info()
    assert info is not None and info.kwargs == {"url": "a"}


async def test_reused_id_of_finished_job_with_kept_result_raises(queue: ArqJobQueue) -> None:
    # Simulate a job that already ran: no longer queued, but arq still keeps its result.
    await queue._pool.set(f"{result_key_prefix}job-done", b"result", ex=3600)
    with pytest.raises(DuplicateJobError):
        await queue.enqueue("import_listing", {"url": "a"}, job_id="job-done")
    assert await queue._pool.queued_jobs() == []


async def test_reserved_payload_keys_are_rejected(queue: ArqJobQueue) -> None:
    with pytest.raises(ValueError, match="_job_id"):
        await queue.enqueue("import_listing", {"_job_id": "x"}, job_id="job-2")


async def test_job_info_pending_and_unknown(queue: ArqJobQueue) -> None:
    await queue.enqueue("import_listing", {"url": "a"}, job_id="job-q")
    assert (await queue.job_info("job-q")).state is QueueJobState.PENDING
    assert (await queue.job_info("never-queued")).state is QueueJobState.UNKNOWN
