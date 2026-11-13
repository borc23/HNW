"""`SourceAdapter` for huurwoningen.nl. Scraped source: personal use only (SOURCES_ENABLED).

Fetching uses curl_cffi with a browser's network fingerprint, because the site answers plain HTTP
clients with 403. Parsing is pyhuurwoningen's, so markup changes are fixed in that one library.
"""

from typing import Any
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession, BrowserType
from curl_cffi.requests.exceptions import RequestException
from curl_cffi.requests.impersonate import resolve_latest_browser_type
from pydantic import ValidationError
from pyhuurwoningen.models import ListingDetails
from pyhuurwoningen.parsing import BASE_URL, DETAIL_PATH, parse_detail_page

from housing_netherlands.core.errors import SourceFetchError, SourceParseError
from housing_netherlands.core.models import FetchedListing, Interior, Listing

NAME = "huurwoningen"
HOSTS = frozenset({"www.huurwoningen.nl", "huurwoningen.nl"})
ACCEPT_LANGUAGE = "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7"


def canonical_url(url: str) -> str | None:
    """The listing's canonical (Dutch) page URL, or None if `url` is not a listing page.

    Query, fragment and the English `/en/` variant all map to one URL, so the same listing
    pasted twice is one row (listings are unique on source + url).
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in HOSTS:
        return None
    match = DETAIL_PATH.match(parts.path)
    if not match:
        return None
    city, listing_id = match.groups()
    slug = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return f"{BASE_URL}/huren/{city}/{listing_id}/{slug}/"


# The site's Dutch values, lower-cased.
_INTERIORS = {
    "kaal": Interior.BARE,
    "gestoffeerd": Interior.UPHOLSTERED,
    "gemeubileerd": Interior.FURNISHED,
}
_CONSTRUCTION = {"nieuwbouw": True, "bestaande bouw": False}


def _lookup[T](table: dict[str, T], value: str | None) -> T | None:
    return table.get(value.strip().lower()) if value else None


def _plausible_year(year: int | None) -> int | None:
    """Typos like 0 or 19655 become unknown; a bad optional field must not fail the import."""
    return year if year is not None and 1000 <= year <= 2100 else None


def to_listing(details: ListingDetails, url: str) -> Listing:
    locality = " ".join(p for p in (details.postcode, details.city) if p)
    return Listing(
        source=NAME,
        source_listing_id=details.id,
        url=url,
        title=details.title,
        price_eur=details.price,
        area_m2=details.area or None,  # 0 m² means "not shown"
        rooms=details.rooms,
        bedrooms=details.bedrooms,
        # The site shows the street without a house number.
        address_text=", ".join(p for p in (details.street, locality) if p) or None,
        postcode=details.postcode,
        city=details.city,
        neighbourhood=details.neighbourhood,
        latitude=details.latitude,
        longitude=details.longitude,
        description=details.description,
        image_url=details.image_url,
        build_year=_plausible_year(details.build_year),
        new_build=_lookup(_CONSTRUCTION, details.construction_type),
        interior=_lookup(_INTERIORS, details.interior),
    )


_BROWSER_PROFILES = frozenset(b.value for b in BrowserType)


def check_impersonate(profile: str) -> str:
    """Validate a curl_cffi browser profile the way curl_cffi does (alias -> versioned target).

    curl_cffi only rejects an unknown profile on the first request, as a RequestException that
    would look like a retryable fetch failure; checking here makes a config typo fail at startup.
    """
    if resolve_latest_browser_type(profile) not in _BROWSER_PROFILES:
        raise ValueError(
            f"HUURWONINGEN_IMPERSONATE={profile!r} is not a curl_cffi browser profile; "
            "use e.g. 'chrome', 'safari', 'firefox', 'edge' or a versioned one like 'chrome124'"
        )
    return profile


class HuurwoningenSource:
    """Holds one HTTP session (connection reuse); release it with `await source.close()`.

    No retries here: a failed fetch raises `SourceFetchError` and the job queue decides
    whether to retry (`SourceFetchError.retryable`).
    """

    name = NAME

    def __init__(
        self,
        *,
        timeout_s: float,
        impersonate: str = "chrome",
        session: Any = None,  # an AsyncSession-like object; tests pass a fake
    ) -> None:
        self._timeout_s = timeout_s
        check_impersonate(impersonate)
        if session is None:
            session = AsyncSession(
                impersonate=impersonate,  # type: ignore[arg-type]  # str, checked above
                headers={"Accept-Language": ACCEPT_LANGUAGE},
            )
        self._session = session

    async def close(self) -> None:
        await self._session.close()

    def can_handle(self, url: str) -> bool:
        return canonical_url(url) is not None

    async def fetch(self, url: str) -> FetchedListing:
        canonical = canonical_url(url)
        if canonical is None:
            raise ValueError(f"not a huurwoningen.nl listing URL: {url!r}")

        try:
            response = await self._session.get(canonical, timeout=self._timeout_s)
        except RequestException as exc:
            raise SourceFetchError(NAME, canonical, f"{type(exc).__name__}: {exc}") from exc

        status = response.status_code
        if status >= 400:
            blocked = status == 403 and response.headers.get("cf-mitigated")
            reason = "blocked by a Cloudflare bot check" if blocked else f"HTTP {status}"
            raise SourceFetchError(NAME, canonical, reason, status=status)

        raw: bytes = response.content
        details = parse_detail_page(raw, canonical)
        if not details.title:
            # e.g. a removed listing that redirects to search results, or changed markup
            raise SourceParseError(NAME, canonical, "page has no listing title")
        try:
            listing = to_listing(details, canonical)
        except ValidationError as exc:
            raise SourceParseError(NAME, canonical, f"unexpected values: {exc}") from exc

        return FetchedListing(
            listing=listing,
            raw=raw,
            raw_content_type=response.headers.get("content-type") or "text/html",
        )
