"""Step 1 end to end: paste a listing URL on the page -> worker -> listing with summary on the page.

Everything is real (API, wiring, arq worker, huurwoningen parser, Postgres, S3, Redis) except the
two outside services: the site's HTTP response is a saved page and the LLM is a fake.
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from housing_netherlands.adapters.source_huurwoningen import HuurwoningenSource
from housing_netherlands.config import Settings
from housing_netherlands.wiring import connect_blob_store
from tests.fakes import HUURWONINGEN_DETAIL_HTML as FIXTURE
from tests.fakes import FakeLLMClient, FakeSession, respond
from tests.integration.worker_runner import Sessions, run_worker_until_idle
from tests.redirects import redirected_job_id

PASTED_URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/?utm_source=mail"
CANONICAL_URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"
SUMMARY = {"summary_en": "Bright 3-room flat.", "key_facts": ["EUR 1450", "72 m2", "3 rooms"]}


def site(*responses: object) -> HuurwoningenSource:
    """The real adapter and parser; only its HTTP session is replaced by saved responses."""
    return HuurwoningenSource(timeout_s=5, session=FakeSession(*responses))


async def test_pasted_url_ends_up_on_the_page_with_its_summary(
    client: TestClient, settings: Settings, sessions: Sessions
) -> None:
    # 1. Paste the URL in the form, as a user would.
    response = client.post("/import", data={"url": PASTED_URL}, follow_redirects=False)
    job_id = redirected_job_id(response)
    job_page = response.headers["location"]
    assert f"Job {job_id}: <strong>queued</strong>" in client.get(job_page).text

    # 2. The worker runs the import.
    source = site(respond(headers={"content-type": "text/html; charset=UTF-8"}))
    llm = FakeLLMClient(json.dumps(SUMMARY))
    await run_worker_until_idle(settings, sessions, source, llm)

    # 3. The page shows the finished job and the listing with its summary.
    page = client.get(job_page).text
    assert f"Job {job_id}: <strong>succeeded</strong>" in page
    assert "Appartement Voorbeeldstraat in Rotterdam" in page
    assert "€1450" in page and "Bright 3-room flat." in page and "<li>72 m2</li>" in page

    # 4. The JSON API agrees, with the fields parsed from the real page.
    [item] = client.get("/api/listings").json()
    listing = item["listing"]
    assert listing["url"] == CANONICAL_URL  # tracking query removed
    assert (listing["price_eur"], listing["area_m2"], listing["rooms"]) == (1450, 72.0, 3)
    assert (listing["latitude"], listing["longitude"]) == (51.8871, 4.4887)
    assert item["summary"] == SUMMARY

    # 5. The exact page that was fetched is archived, and the listing points at it.
    async with sessions() as s:
        raw_key = await s.scalar(text("SELECT raw_blob_key FROM listings"))
    blobs = await connect_blob_store(settings)
    try:
        assert await blobs.get(raw_key) == FIXTURE
    finally:
        await blobs.close()


async def test_second_import_of_the_same_listing_reuses_the_summary(
    client: TestClient, settings: Settings, sessions: Sessions
) -> None:
    llm = FakeLLMClient(json.dumps(SUMMARY))  # one reply only: a second LLM call would fail
    for url in (CANONICAL_URL, PASTED_URL):  # same listing, pasted two ways
        client.post("/api/listings/import", json={"url": url})
        await run_worker_until_idle(settings, sessions, site(respond()), llm)

    assert len(llm.calls) == 1
    async with sessions() as s:
        statuses = (await s.scalars(text("SELECT status FROM jobs_log"))).all()
        listings = await s.scalar(text("SELECT count(*) FROM listings"))
        summaries = await s.scalar(text("SELECT count(*) FROM listing_enrichments"))
    assert statuses == ["succeeded", "succeeded"]
    assert (listings, summaries) == (1, 1)


async def test_removed_listing_shows_as_failed_on_the_page(
    client: TestClient, settings: Settings, sessions: Sessions
) -> None:
    job_id = client.post("/api/listings/import", json={"url": CANONICAL_URL}).json()["job_id"]
    await run_worker_until_idle(settings, sessions, site(respond(404, b"")), FakeLLMClient())

    page = client.get(f"/?job={job_id}").text
    assert f"Job {job_id}: <strong>failed</strong>" in page and "HTTP 404" in page
    assert "No listings yet." in page
