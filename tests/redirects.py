"""Read the page form's redirect without depending on its exact format."""

from urllib.parse import parse_qs, urlsplit

from httpx import Response


def redirect_query(response: Response) -> dict[str, str]:
    """Query parameters of a 303 redirect's Location (relative or absolute URL)."""
    assert response.status_code == 303, f"expected a 303 redirect, got {response.status_code}"
    location = response.headers["location"]
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def redirected_job_id(response: Response) -> str:
    query = redirect_query(response)
    assert "job" in query, f"redirect has no job id: {response.headers['location']!r}"
    return query["job"]
