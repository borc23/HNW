"""Against the real huurwoningen.nl: catches markup changes and bot blocks the fixture can't.

Needs internet, not the Compose stack. Two requests: one search page, one listing.
Opt-in (`RUN_LIVE_TESTS=1 uv run pytest tests/live`): personal use only, never on CI.
"""

import pytest
from pyhuurwoningen.parsing import parse_search_page

from housing_netherlands.adapters.source_huurwoningen import HuurwoningenSource

pytestmark = pytest.mark.live


@pytest.fixture
async def source():
    source = HuurwoningenSource(timeout_s=30)
    yield source
    await source.close()


async def test_fetches_and_parses_a_current_rotterdam_listing(source: HuurwoningenSource) -> None:
    search = await source._session.get("https://www.huurwoningen.nl/in/rotterdam/", timeout=30)
    assert search.status_code == 200, f"search page: HTTP {search.status_code}"
    cards = parse_search_page(search.content)
    assert cards, "no listings on the search page: markup changed?"

    fetched = await source.fetch(cards[0].url)

    listing = fetched.listing
    assert listing.source_listing_id == cards[0].id
    assert listing.title
    assert listing.price_eur and listing.price_eur > 0
    assert listing.city == "Rotterdam"
    assert listing.latitude is not None and listing.longitude is not None
    assert fetched.raw_content_type.startswith("text/html")
    assert len(fetched.raw) > 10_000
