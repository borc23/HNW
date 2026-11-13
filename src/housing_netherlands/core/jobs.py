"""Queue-independent job handler types: the worker runner adapts these to its queue backend."""

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobContext:
    job_id: str
    attempt: int  # 1 for the first try
    state: MutableMapping[str, Any]  # per-process resources set up at worker startup


# A handler raises `RetryLater` to be run again; any other exception fails the job.
JobHandler = Callable[[JobContext, dict[str, Any]], Awaitable[Any]]
Lifecycle = Callable[[MutableMapping[str, Any]], Awaitable[None]]
