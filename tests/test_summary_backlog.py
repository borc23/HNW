import json
from itertools import count

from housing_netherlands.core.errors import LLMUnavailableError
from housing_netherlands.core.importing import ImportDeps
from housing_netherlands.core.models import LLMParams, LLMResponse
from housing_netherlands.core.summary_backlog import summarize_pending
from tests.fakes import (
    FakeBlobStore,
    FakeJobLog,
    FakeListingRepository,
    FakeLLMClient,
    make_listing,
)

SUMMARY = json.dumps({"summary_en": "Bright flat.", "key_facts": ["EUR 915", "50 m2", "balcony"]})
BASE = "https://www.huurwoningen.nl/huren/rotterdam"


class DownLLM(FakeLLMClient):
    async def complete(self, messages, *, params, json_schema=None) -> LLMResponse:  # type: ignore[override]
        raise LLMUnavailableError(params.model, "connection refused")


async def deps_with_pending(llm: FakeLLMClient, n: int) -> tuple[ImportDeps, list[int]]:
    repo = FakeListingRepository()
    ids = []
    for i in range(n):
        listing = make_listing(source_listing_id=f"l{i}", url=f"{BASE}/l{i}/x/", title=f"Flat {i}")
        listing_id = await repo.upsert_listing(listing, raw_blob_key="k")
        await repo.mark_summary_pending(listing_id)
        ids.append(listing_id)
    deps = ImportDeps(
        listings=repo,
        job_log=FakeJobLog(),
        blobs=FakeBlobStore(),
        llm=llm,
        sources=[],
        llm_params=LLMParams(model="fake"),
    )
    return deps, ids


async def test_summarises_pending_newest_first_and_clears_the_flag() -> None:
    llm = FakeLLMClient(SUMMARY, SUMMARY)
    deps, ids = await deps_with_pending(llm, 2)

    assert await summarize_pending(deps, budget_s=60) == 2

    assert await deps.listings.pending_summaries(limit=10) == []
    first_prompt = llm.calls[0][1].content
    assert "Flat 1" in first_prompt  # newest (highest id in the fake) first
    for listing_id in ids:
        view = await deps.listings.get_view(listing_id)
        assert view is not None and view.summary is not None


async def test_stops_when_the_budget_is_spent() -> None:
    deps, _ = await deps_with_pending(FakeLLMClient(SUMMARY, SUMMARY), 2)
    ticks = count()  # each clock() call advances one second
    assert await summarize_pending(deps, budget_s=1.5, clock=lambda: next(ticks)) == 1
    assert len(await deps.listings.pending_summaries(limit=10)) == 1


async def test_llm_down_stops_and_keeps_the_flag() -> None:
    deps, ids = await deps_with_pending(DownLLM(), 2)
    assert await summarize_pending(deps, budget_s=60) == 0
    assert sorted(await deps.listings.pending_summaries(limit=10)) == ids


async def test_a_listing_that_cannot_be_summarised_does_not_block_the_rest() -> None:
    # invalid JSON twice for the newest listing (one retry), then a good one for the next
    deps, ids = await deps_with_pending(FakeLLMClient("nope", "still nope", SUMMARY), 2)
    assert await summarize_pending(deps, budget_s=60) == 1
    assert await deps.listings.pending_summaries(limit=10) == []
    assert (await deps.listings.get_view(ids[0])).summary is not None  # type: ignore[union-attr]
    assert (await deps.listings.get_view(ids[1])).summary is None  # type: ignore[union-attr]
