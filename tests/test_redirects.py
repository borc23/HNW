import httpx
import pytest

from tests.redirects import redirect_query, redirected_job_id


def _redirect(location: str, status: int = 303) -> httpx.Response:
    return httpx.Response(status, headers={"location": location})


@pytest.mark.parametrize(
    "location",
    [
        "/?job=abc123",
        "/?url=https%3A%2F%2Fx.nl%2Fa%3Fb%3D1&job=abc123",  # extra parameter first
        "http://localhost:8000/?job=abc123",  # absolute URL
    ],
)
def test_job_id_is_found_whatever_the_format(location: str) -> None:
    assert redirected_job_id(_redirect(location)) == "abc123"


def test_missing_job_id_fails_with_a_clear_message() -> None:
    with pytest.raises(AssertionError, match="redirect has no job id: '/\\?error=bad'"):
        redirected_job_id(_redirect("/?error=bad"))


def test_non_redirect_fails_clearly() -> None:
    with pytest.raises(AssertionError, match="expected a 303 redirect, got 200"):
        redirect_query(_redirect("/", status=200))
