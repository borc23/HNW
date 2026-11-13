"""Domain errors raised through ports, so callers can handle them without knowing the adapter."""

from typing import Any


def _restore(cls: type["DomainError"], args: tuple[Any, ...], state: dict[str, Any]) -> Any:
    error = cls.__new__(cls)
    error.args = args
    error.__dict__.update(state)
    return error


class DomainError(Exception):
    """Base for domain errors. Picklable whatever the subclass constructor looks like.

    arq pickles an exception that escapes a job as the job's result. Default exception pickling
    re-calls `cls(*self.args)`, i.e. with only the formatted message, which fails for
    constructors with several or keyword-only arguments. Restoring without `__init__` keeps the
    message and every attribute (e.g. `status`, so `retryable` still works).
    """

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self.args, self.__dict__.copy()))


class DuplicateJobError(DomainError):
    """A job with this id is already queued, running, or its result is still retained."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id!r} already exists")
        self.job_id = job_id


class SourceError(DomainError):
    """A listing could not be read from its source site."""

    def __init__(self, source: str, url: str, reason: str) -> None:
        super().__init__(f"{source}: {reason} ({url})")
        self.source = source
        self.url = url
        self.reason = reason


class SourceFetchError(SourceError):
    """The page could not be downloaded: network error, HTTP error status or bot block."""

    # Worth retrying later: no response at all, a bot block, rate limiting, or a server error.
    _RETRYABLE_STATUSES = frozenset({403, 408, 425, 429})

    def __init__(self, source: str, url: str, reason: str, *, status: int | None = None) -> None:
        super().__init__(source, url, reason)
        self.status = status

    @property
    def retryable(self) -> bool:
        """False for permanent failures, e.g. 404/410 when the listing was taken down."""
        return self.status is None or self.status >= 500 or self.status in self._RETRYABLE_STATUSES


class SourceParseError(SourceError):
    """The page was downloaded but is not a readable listing (removed, or the markup changed).

    Not retryable: the same page will fail the same way.
    """


class LLMOutputInvalid(DomainError):
    """The model's output failed schema validation on every attempt."""

    def __init__(self, prompt_version: str, errors: list[str]) -> None:
        super().__init__(
            f"{prompt_version}: invalid output after {len(errors)} attempts: {errors[-1]}"
        )
        self.prompt_version = prompt_version
        self.errors = errors


class UnsupportedUrlError(DomainError):
    """No enabled source handles this URL (unknown site, not a listing page, or disabled)."""

    def __init__(self, url: str) -> None:
        super().__init__(f"no enabled source handles {url!r}")
        self.url = url


class RetryLater(DomainError):
    """A job attempt failed temporarily; the queue should run it again after `delay_s`."""

    def __init__(self, delay_s: float, reason: str) -> None:
        super().__init__(f"retry in {delay_s:g} s: {reason}")
        self.delay_s = delay_s
        self.reason = reason


class LLMUnavailableError(DomainError):
    """The model could not be reached or was temporarily overloaded (connection refused,
    timeout, rate limit, 5xx). Worth retrying later; the request itself was fine."""

    retryable = True

    def __init__(self, model: str, reason: str) -> None:
        super().__init__(f"{model}: {reason}")
        self.model = model
        self.reason = reason


class EnqueueFailedError(DomainError):
    """The job was logged (and is now FAILED in `jobs_log`) but could not be queued."""

    def __init__(self, job_id: str, reason: str) -> None:
        super().__init__(f"job {job_id} could not be queued: {reason}")
        self.job_id = job_id
        self.reason = reason
