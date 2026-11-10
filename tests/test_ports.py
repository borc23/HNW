import pytest

from housing_netherlands.core import ports
from housing_netherlands.core.models import FetchedListing, JobStatus, ListingSummary
from tests.fakes import (
    FakeBlobStore,
    FakeJobLog,
    FakeJobQueue,
    FakeListingRepository,
    FakeLLMClient,
    FakeSourceAdapter,
)
from tests.test_core_models import make_listing


@pytest.mark.parametrize(
    "fake,port",
    [
        (FakeJobQueue(), ports.JobQueue),
        (FakeBlobStore(), ports.BlobStore),
        (FakeLLMClient(), ports.LLMClient),
        (FakeSourceAdapter("huurwoningen", "huurwoningen.nl"), ports.SourceAdapter),
        (FakeListingRepository(), ports.ListingRepository),
        (FakeJobLog(), ports.JobLog),
    ],
)
def test_fakes_implement_ports(fake: object, port: type) -> None:
    assert isinstance(fake, port)


async def test_fake_repository_round_trip() -> None:
    repo = FakeListingRepository()
    listing = make_listing()
    first = await repo.upsert_listing(listing, raw_blob_key="raw/1.json")
    again = await repo.upsert_listing(listing, raw_blob_key="raw/2.json")
    assert first == again == 1

    summary = ListingSummary(summary_en="ok", key_facts=["a", "b", "c"])
    await repo.save_enrichment(
        first, prompt_version="v1", content_hash="h", model="m", output=summary
    )
    assert await repo.find_enrichment(first, prompt_version="v1", content_hash="h") == summary
    assert await repo.find_enrichment(first, prompt_version="v2", content_hash="h") is None

    views = await repo.list_listings()
    assert views[0].summary == summary


async def test_fake_source_and_job_log() -> None:
    fetched = FetchedListing(listing=make_listing(), raw=b"{}")
    source = FakeSourceAdapter("huurwoningen", "huurwoningen.nl", fetched)
    assert source.can_handle("https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/")
    assert not source.can_handle("https://www.example.com/x")
    assert await source.fetch("https://www.huurwoningen.nl/x") == fetched

    log = FakeJobLog()
    await log.record("j1", job_type="import_listing", status=JobStatus.RUNNING)
    await log.record("j1", job_type="import_listing", status=JobStatus.FAILED, error="boom")
    assert log.records["j1"][-1] == ("import_listing", JobStatus.FAILED, "boom")
