"""summary-v1: English summary + exactly 3 key facts for one rental listing.

Only listing facts go into the prompt (never user data), and not the URL or source site,
so the same home listed on two sites renders identically and hits the same cache entry.
"""

from housing_netherlands.core.models import Listing, ListingSummary, LLMMessage

PROMPT_VERSION = "summary-v1"
OUTPUT_SCHEMA = ListingSummary
MAX_DESCRIPTION_CHARS = 4000

SYSTEM = """\
You summarise Dutch rental listings for an English-speaking tenant.
Use only facts stated in the listing; never guess or add information.
Reply with JSON only, matching this shape:
{"summary_en": "<2-3 sentence summary in English>",
 "key_facts": ["<fact>", "<fact>", "<fact>"]}
key_facts must contain exactly 3 short facts that matter most to a tenant, e.g. total monthly
cost, size and rooms, availability, or conditions such as pets, smoking or income requirements."""


def _fmt(value: object, unit: str = "") -> str:
    return "unknown" if value is None else f"{value}{unit}"


def build_messages(listing: Listing) -> list[LLMMessage]:
    description = (listing.description or "").strip()[:MAX_DESCRIPTION_CHARS] or "(none)"
    user = "\n".join(
        [
            f"Title: {listing.title}",
            f"City: {_fmt(listing.city)}",
            f"Postcode: {_fmt(listing.postcode)}",
            f"Rent: {_fmt(listing.price_eur, ' EUR/month')}",
            f"Living area: {_fmt(listing.area_m2, ' m2')}",
            f"Rooms: {_fmt(listing.rooms)}",
            f"Bedrooms: {_fmt(listing.bedrooms)}",
            "Description (may be Dutch):",
            description,
        ]
    )
    return [LLMMessage(role="system", content=SYSTEM), LLMMessage(role="user", content=user)]
