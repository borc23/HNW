"""Domain errors raised through ports, so callers can handle them without knowing the adapter."""


class DuplicateJobError(Exception):
    """A job with this id is already queued, running, or its result is still retained."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id!r} already exists")
        self.job_id = job_id
