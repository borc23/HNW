"""Domain errors raised through ports, so callers can handle them without knowing the adapter."""


class DuplicateJobError(Exception):
    """A job with this id is already queued, running, or its result is still retained."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id!r} already exists")
        self.job_id = job_id


class SourceError(Exception):
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


class LLMOutputInvalid(Exception):
    """The model's output failed schema validation on every attempt."""

    def __init__(self, prompt_version: str, errors: list[str]) -> None:
        super().__init__(
            f"{prompt_version}: invalid output after {len(errors)} attempts: {errors[-1]}"
        )
        self.prompt_version = prompt_version
        self.errors = errors
