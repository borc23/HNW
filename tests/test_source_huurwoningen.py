"""HuurwoningenSource with a fake HTTP session: URL handling, parsing and error mapping."""

from contextlib import AsyncExitStack
from typing import Any

import pytest
from curl_cffi.requests.exceptions import Timeout
from pyhuurwoningen.models import ListingDetails

from housing_netherlands.adapters.source_huurwoningen import (
    HuurwoningenSource,
    canonical_url,
    check_impersonate,
    to_listing,
)
from housing_netherlands.config import Settings
from housing_netherlands.core import ports
from housing_netherlands.core.errors import SourceFetchError, SourceParseError
from housing_netherlands.core.models import Interior
from housing_netherlands.wiring import build_sources
from tests.fakes import HUURWONINGEN_DETAIL_HTML as FIXTURE
from tests.fakes import FakeSession, respond

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"


def make_source(*responses: Any) -> tuple[HuurwoningenSource, FakeSession]:
    session = FakeSession(*responses)
    return HuurwoningenSource(timeout_s=7, session=session), session


def test_implements_port() -> None:
    source, _ = make_source()
    assert isinstance(source, ports.SourceAdapter)
    assert source.name == "huurwoningen"


@pytest.mark.parametrize(
    "url",
    [
        URL,
        "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein",
        "http://huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/?utm_source=x#fotos",
        "https://www.huurwoningen.nl/en/huren/rotterdam/ea81e68d/zuidplein/",
        "  https://WWW.Huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/ ",
    ],
)
def test_listing_urls_map_to_one_canonical_url(url: str) -> None:
    assert canonical_url(url) == URL
    assert make_source()[0].can_handle(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.huurwoningen.nl/in/rotterdam/",  # search page
        "https://www.huurwoningen.nl/",
        "https://www.pararius.nl/huren/rotterdam/ea81e68d/zuidplein/",
        "https://evil.example/huren/rotterdam/ea81e68d/zuidplein/?huurwoningen.nl",
        "https://www.huurwoningen.nl.evil.example/huren/rotterdam/ea81e68d/zuidplein/",
        "ftp://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/",
        "not a url",
    ],
)
def test_other_urls_are_not_handled(url: str) -> None:
    assert canonical_url(url) is None
    assert not make_source()[0].can_handle(url)


async def test_fetch_parses_listing_and_keeps_raw_page() -> None:
    source, session = make_source(respond(headers={"content-type": "text/html; charset=UTF-8"}))
    fetched = await source.fetch(URL + "?utm_source=mail")

    assert session.requests == [(URL, 7)]  # canonical URL, configured timeout
    assert fetched.raw == FIXTURE
    assert fetched.raw_content_type == "text/html; charset=UTF-8"
    listing = fetched.listing
    assert (listing.source, listing.source_listing_id, listing.url) == (
        "huurwoningen",
        "ea81e68d",
        URL,
    )
    assert listing.title == "Appartement Voorbeeldstraat in Rotterdam"
    assert (listing.price_eur, listing.area_m2, listing.rooms, listing.bedrooms) == (1450, 72, 3, 2)
    assert listing.address_text == "Voorbeeldstraat, 3083CR Rotterdam"
    assert (listing.postcode, listing.city) == ("3083CR", "Rotterdam")
    assert listing.neighbourhood == "Zuidplein"
    assert (listing.latitude, listing.longitude) == (51.8871, 4.4887)
    assert listing.description is not None and listing.description.startswith("Licht 3-kamer")


@pytest.mark.parametrize(
    ("construction", "interior", "new_build", "expected_interior"),
    [
        ("Nieuwbouw", "Gemeubileerd", True, Interior.FURNISHED),
        ("Bestaande bouw", "Kaal", False, Interior.BARE),
        (" nieuwbouw ", "Gestoffeerd", True, Interior.UPHOLSTERED),
        (None, None, None, None),
        ("Renovatie", "Anders", None, None),  # unknown values stay unknown
    ],
)
def test_search_fields_are_normalised(
    construction: str | None,
    interior: str | None,
    new_build: bool | None,
    expected_interior: Interior | None,
) -> None:
    details = ListingDetails(
        id="x",
        url=URL,
        title="T",
        build_year=2021,
        construction_type=construction,
        interior=interior,
    )
    listing = to_listing(details, URL)
    assert (listing.build_year, listing.new_build, listing.interior) == (
        2021,
        new_build,
        expected_interior,
    )


def test_main_photo_is_kept() -> None:
    details = ListingDetails(id="x", url=URL, title="T", image_url="https://cdn.example/1.jpg")
    assert to_listing(details, URL).image_url == "https://cdn.example/1.jpg"


async def test_missing_content_type_defaults_to_html() -> None:
    source, _ = make_source(respond())
    assert (await source.fetch(URL)).raw_content_type == "text/html"


async def test_fetch_rejects_urls_it_cannot_handle() -> None:
    source, session = make_source()
    with pytest.raises(ValueError, match=r"not a huurwoningen\.nl listing URL"):
        await source.fetch("https://www.pararius.nl/x")
    assert session.requests == []


@pytest.mark.parametrize(
    ("status", "headers", "reason", "retryable"),
    [
        (404, {}, "HTTP 404", False),
        (410, {}, "HTTP 410", False),
        (403, {"cf-mitigated": "challenge"}, "Cloudflare bot check", True),
        (429, {}, "HTTP 429", True),
        (503, {}, "HTTP 503", True),
    ],
)
async def test_http_errors_become_source_fetch_error(
    status: int, headers: dict[str, str], reason: str, retryable: bool
) -> None:
    source, _ = make_source(respond(status, b"", headers))
    with pytest.raises(SourceFetchError, match=reason) as info:
        await source.fetch(URL)
    assert (info.value.status, info.value.retryable, info.value.url) == (status, retryable, URL)


async def test_network_errors_become_retryable_source_fetch_error() -> None:
    source, _ = make_source(Timeout("timed out after 7s"))
    with pytest.raises(SourceFetchError, match="Timeout") as info:
        await source.fetch(URL)
    assert info.value.status is None
    assert info.value.retryable
    assert isinstance(info.value.__cause__, Timeout)


async def test_page_without_listing_is_a_parse_error() -> None:
    # e.g. a removed listing that redirects to search results
    source, _ = make_source(respond(content=b"<html><h1>Huurwoningen in Rotterdam</h1></html>"))
    with pytest.raises(SourceParseError, match="no listing title"):
        await source.fetch(URL)


async def test_out_of_range_values_are_a_parse_error() -> None:
    page = FIXTURE.replace(b'"latitude":51.8871', b'"latitude":518871')
    source, _ = make_source(respond(content=page))
    with pytest.raises(SourceParseError, match="unexpected values"):
        await source.fetch(URL)


async def test_close_closes_the_session() -> None:
    source, session = make_source()
    await source.close()
    assert session.closed


# --- impersonate profile: checked at startup, not on the first fetch ---------------------


@pytest.mark.parametrize("profile", ["chrome", "safari", "firefox", "edge", "chrome124"])
def test_valid_impersonate_profiles_are_accepted(profile: str) -> None:
    assert check_impersonate(profile) == profile
    HuurwoningenSource(timeout_s=1, impersonate=profile, session=FakeSession())


@pytest.mark.parametrize("profile", ["chrom", "Chrome", "", "chrome9999", "netscape"])
def test_unknown_impersonate_profile_fails_at_construction(profile: str) -> None:
    with pytest.raises(ValueError, match="HUURWONINGEN_IMPERSONATE"):
        HuurwoningenSource(timeout_s=1, impersonate=profile, session=FakeSession())


async def test_typo_in_settings_stops_startup() -> None:
    settings = Settings(huurwoningen_impersonate="chrom")  # type: ignore[call-arg]
    async with AsyncExitStack() as stack:
        with pytest.raises(ValueError, match="'chrom' is not a curl_cffi browser profile"):
            build_sources(settings, stack)


def test_default_profile_is_valid() -> None:
    check_impersonate(Settings().huurwoningen_impersonate)
