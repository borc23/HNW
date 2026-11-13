"""API and test page with in-memory fake adapters (no services needed)."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from housing_netherlands.api.app import create_app
from housing_netherlands.core.models import Interior, JobStatus, ListingFilters, ListingSummary
from housing_netherlands.wiring import Adapters
from tests.fakes import (
    FakeBlobStore,
    FakeJobLog,
    FakeJobQueue,
    FakeListingRepository,
    FakeLLMClient,
    FakeSourceAdapter,
    make_listing,
)
from tests.redirects import redirected_job_id

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"


@pytest.fixture
def adapters() -> Adapters:
    return Adapters(
        listings=FakeListingRepository(),
        job_log=FakeJobLog(),
        blobs=FakeBlobStore(),
        queue=FakeJobQueue(),
        llm=FakeLLMClient(),
        sources=(FakeSourceAdapter("huurwoningen", "huurwoningen.nl"),),
    )


@pytest.fixture
def client(adapters: Adapters) -> Iterator[TestClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Adapters]:
        yield adapters

    with TestClient(create_app(factory)) as c:  # `with` runs the lifespan
        yield c


def queued(adapters: Adapters) -> list:
    return adapters.queue.jobs  # type: ignore[attr-defined]


# --- JSON API -------------------------------------------------------------------------------


def test_healthz_and_request_id(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.json() == {"status": "ok"}
    assert len(response.headers["X-Request-ID"]) == 32
    echoed = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"


def test_import_queues_a_job(client: TestClient, adapters: Adapters) -> None:
    response = client.post("/api/listings/import", json={"url": f"  {URL}  "})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    payload = {"url": URL, "summarize_now": True}  # URL stripped; summarised inline
    assert queued(adapters) == [("import_listing", payload, job_id)]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job == {
        "job_id": job_id,
        "job_type": "import_listing",
        "status": "queued",
        "error": None,
    }


def test_import_of_unsupported_url_is_rejected(client: TestClient, adapters: Adapters) -> None:
    response = client.post("/api/listings/import", json={"url": "https://www.funda.nl/huur/x"})
    assert response.status_code == 422
    assert "no enabled source handles" in response.json()["detail"]
    assert queued(adapters) == []


@pytest.mark.parametrize("body", [{}, {"url": ""}, {"url": "x" * 2049}])
def test_import_validates_the_body(client: TestClient, body: dict) -> None:
    assert client.post("/api/listings/import", json=body).status_code == 422


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/jobs/nope").status_code == 404


async def test_listings_endpoint(client: TestClient, adapters: Adapters) -> None:
    listing_id = await adapters.listings.upsert_listing(make_listing(), raw_blob_key="k")
    summary = ListingSummary(summary_en="Bright flat.", key_facts=["EUR 915", "50 m2", "balcony"])
    await adapters.listings.save_enrichment(
        listing_id, prompt_version="v1", content_hash="h", model="m", output=summary
    )
    [item] = client.get("/api/listings").json()
    assert item["id"] == listing_id
    assert item["listing"]["title"] == "Appartement Zuidplein"
    assert item["summary"]["key_facts"] == ["EUR 915", "50 m2", "balcony"]


def test_listings_endpoint_passes_filters(client: TestClient, adapters: Adapters) -> None:
    query = (
        "place=Zuidplein&max_rent=1500&min_rooms=2&min_area=40&new_build=true&interior=furnished"
    )
    assert client.get(f"/api/listings?limit=10&{query}").status_code == 200
    assert adapters.listings.last_filters == ListingFilters(  # type: ignore[attr-defined]
        place="Zuidplein",
        max_rent=1500,
        min_rooms=2,
        min_area=40,
        new_build=True,
        interior=Interior.FURNISHED,
    )


@pytest.mark.parametrize(
    "query", ["interior=sofa", "max_rent=-1", "min_rooms=two", "place=", "place=%20%20"]
)
def test_listings_endpoint_rejects_bad_filters(client: TestClient, query: str) -> None:
    assert client.get(f"/api/listings?{query}").status_code == 422


async def test_places_endpoint(client: TestClient, adapters: Adapters) -> None:
    await adapters.listings.upsert_listing(
        make_listing(neighbourhood="Zuidplein"), raw_blob_key="k"
    )
    assert client.get("/api/places").json() == ["Rotterdam", "Zuidplein"]
    assert client.get("/api/places?limit=1").json() == ["Rotterdam"]


@pytest.mark.parametrize("limit", [0, 501])
def test_places_limit_is_bounded(client: TestClient, limit: int) -> None:
    assert client.get(f"/api/places?limit={limit}").status_code == 422


@pytest.mark.parametrize("limit", [0, 201])
def test_listings_limit_is_bounded(client: TestClient, limit: int) -> None:
    assert client.get(f"/api/listings?limit={limit}").status_code == 422


# --- HTML page -------------------------------------------------------------------------------


def test_page_renders_empty_state(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert '<form method="post" action="/import">' in response.text
    assert "No listings yet." in response.text


def test_form_import_redirects_to_job_status(client: TestClient, adapters: Adapters) -> None:
    response = client.post("/import", data={"url": URL}, follow_redirects=False)
    [(_, _, job_id)] = queued(adapters)
    assert redirected_job_id(response) == job_id

    page = client.get(response.headers["location"]).text
    assert f"Job {job_id}: <strong>queued</strong>" in page


def test_form_import_error_is_shown_escaped(client: TestClient, adapters: Adapters) -> None:
    response = client.post("/import", data={"url": "https://evil.example/<script>"})
    assert response.status_code == 200  # followed the redirect
    assert "<strong>Error:</strong> no enabled source handles" in response.text
    assert "<script>" not in response.text and "&lt;script&gt;" in response.text
    assert queued(adapters) == []


async def test_page_lists_listings_with_summary_or_pending(
    client: TestClient, adapters: Adapters
) -> None:
    await adapters.listings.upsert_listing(make_listing(title="Flat <b>A</b>"), raw_blob_key="k")
    page = client.get("/").text
    assert "Listings (1)" in page
    assert "Flat &lt;b&gt;A&lt;/b&gt;" in page  # titles from the site are escaped
    assert "€915" in page and "summary pending" in page


async def test_page_shows_failed_job_error(client: TestClient, adapters: Adapters) -> None:
    await adapters.job_log.record(
        "j1", job_type="import_listing", status=JobStatus.FAILED, error="HTTP 404"
    )
    page = client.get("/?job=j1").text
    assert "Job j1: <strong>failed</strong>" in page and "(HTTP 404)" in page


# --- form failures always come back as the page, never raw JSON or a bare 500 --------------


def _break_queue(adapters: Adapters) -> None:
    async def down(*args: object, **kwargs: object) -> None:
        raise ConnectionError("redis down")

    adapters.queue.enqueue = down  # type: ignore[method-assign]


@pytest.mark.parametrize("data", [{"url": "x" * 2049}, {"url": "   "}, {}])
def test_form_rejects_bad_input_on_the_page(
    client: TestClient, adapters: Adapters, data: dict
) -> None:
    response = client.post("/import", data=data)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<strong>Error:</strong> enter a listing URL of at most 2048 characters" in response.text
    assert queued(adapters) == []


def test_form_with_queue_down_shows_the_failed_job(client: TestClient, adapters: Adapters) -> None:
    _break_queue(adapters)
    response = client.post("/import", data={"url": URL}, follow_redirects=False)
    job_id = redirected_job_id(response)

    page = client.get(response.headers["location"]).text
    assert f"Job {job_id}: <strong>failed</strong>" in page
    assert "enqueue: redis down" in page


def test_form_with_unexpected_error_shows_an_error_line(
    client: TestClient, adapters: Adapters
) -> None:
    async def db_down(*args: object, **kwargs: object) -> None:
        raise OSError("database down")

    adapters.job_log.record = db_down  # type: ignore[method-assign]
    response = client.post("/import", data={"url": URL})
    assert response.status_code == 200
    assert "could not queue the import; try again" in response.text
    assert "database down" not in response.text  # details go to the log, not the page


def test_api_with_queue_down_returns_503_with_job_id(
    client: TestClient, adapters: Adapters
) -> None:
    _break_queue(adapters)
    response = client.post("/api/listings/import", json={"url": URL})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert client.get(f"/api/jobs/{detail['job_id']}").json()["status"] == "failed"
    assert "ConnectionError: redis down" in detail["error"]
