from typing import Any, Self

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from housing_netherlands.core.errors import DuplicateJobError


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

    async def close(self) -> None:
        await self._pool.aclose()
