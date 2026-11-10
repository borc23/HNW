import pytest
from pydantic import ValidationError

from housing_netherlands.core.models import FetchedListing, Listing, ListingSummary


def make_listing(**overrides) -> Listing:
    data = {
        "source": "huurwoningen",
        "source_listing_id": "ea81e68d",
        "url": "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/",
        "title": "Appartement Zuidplein",
        "price_eur": 915,
        "area_m2": 50.0,
        "rooms": 3,
        "postcode": "3083CR",
        "city": "Rotterdam",
        "latitude": 51.88,
        "longitude": 4.49,
    }
    return Listing(**{**data, **overrides})


def test_listing_is_immutable() -> None:
    listing = make_listing()
    with pytest.raises(ValidationError):
        listing.price_eur = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [("price_eur", -1), ("area_m2", 0), ("latitude", 91), ("longitude", -181)],
)
def test_listing_rejects_impossible_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_listing(**{field: value})


def test_listing_optional_fields_default_to_none() -> None:
    listing = Listing(
        source="huurwoningen", source_listing_id="1", url="https://www.huurwoningen.nl/x", title="x"
    )
    assert listing.price_eur is None
    assert listing.description is None


def test_fetched_listing_defaults_to_json_raw() -> None:
    fetched = FetchedListing(listing=make_listing(), raw=b"{}")
    assert fetched.raw_content_type == "application/json"


def test_summary_requires_exactly_three_facts() -> None:
    ListingSummary(summary_en="Nice flat.", key_facts=["a", "b", "c"])
    for facts in (["a", "b"], ["a", "b", "c", "d"]):
        with pytest.raises(ValidationError):
            ListingSummary(summary_en="Nice flat.", key_facts=facts)


def test_summary_validates_llm_json() -> None:
    raw = '{"summary_en": "Bright 2-bed.", "key_facts": ["62 m2", "EUR 1450", "balcony"]}'
    assert ListingSummary.model_validate_json(raw).key_facts[2] == "balcony"
