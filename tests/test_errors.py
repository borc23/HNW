"""Domain errors survive pickling, which is how arq stores an exception as a job's result."""

import pickle

import pytest
from arq.jobs import deserialize_result, serialize_result

from housing_netherlands.core import errors
from housing_netherlands.core.errors import (
    DomainError,
    DuplicateJobError,
    LLMOutputInvalid,
    RetryLater,
    SourceError,
    SourceFetchError,
    SourceParseError,
    UnsupportedUrlError,
)

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"
CASES = [
    SourceFetchError("huurwoningen", URL, "HTTP 503", status=503),
    SourceFetchError("huurwoningen", URL, "HTTP 404", status=404),
    SourceFetchError("huurwoningen", URL, "connection reset"),
    SourceParseError("huurwoningen", URL, "no JSON-LD on page"),
    DuplicateJobError("job-1"),
    LLMOutputInvalid("summary-v1", ["not json", "key_facts: too short"]),
    UnsupportedUrlError("https://example.com/x"),
    RetryLater(30.0, "huurwoningen: HTTP 503"),
]


def _all_subclasses(cls: type) -> set[type]:
    return {sub for direct in cls.__subclasses__() for sub in {direct, *_all_subclasses(direct)}}


def test_every_domain_error_is_covered() -> None:
    # A new error class must be added to CASES, so its pickling is tested too.
    base_only = {SourceError}  # never raised itself, only its subclasses
    defined = {c for c in _all_subclasses(DomainError) if c.__module__ == errors.__name__}
    assert defined - base_only == {type(e) for e in CASES}


def _assert_same(restored: BaseException, original: BaseException) -> None:
    assert type(restored) is type(original)
    assert str(restored) == str(original)
    assert restored.args == original.args
    assert restored.__dict__ == original.__dict__


@pytest.mark.parametrize("error", CASES, ids=lambda e: f"{type(e).__name__}:{e}")
def test_pickle_round_trip_keeps_message_and_attributes(error: DomainError) -> None:
    _assert_same(pickle.loads(pickle.dumps(error)), error)


@pytest.mark.parametrize("error", CASES, ids=lambda e: f"{type(e).__name__}:{e}")
def test_arq_job_result_round_trip(error: DomainError) -> None:
    # The real path: a job raises, arq serializes the exception as the result, a reader loads it.
    data = serialize_result(
        function="import_listing",
        args=(),
        kwargs={"url": URL},
        job_try=1,
        enqueue_time_ms=0,
        success=False,
        result=error,
        start_ms=0,
        finished_ms=1,
        ref="job-1",
        queue_name="arq:queue",
        job_id="job-1",
    )
    assert data is not None
    result = deserialize_result(data)
    assert result.success is False
    _assert_same(result.result, error)


def test_restored_fetch_error_keeps_retry_decision() -> None:
    temporary, gone = CASES[0], CASES[1]
    assert isinstance(temporary, SourceFetchError) and isinstance(gone, SourceFetchError)
    assert pickle.loads(pickle.dumps(temporary)).retryable is True
    assert pickle.loads(pickle.dumps(gone)).retryable is False
