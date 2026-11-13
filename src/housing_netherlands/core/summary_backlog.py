"""Background summaries: work through listings flagged `summary_pending`, one LLM call at a time.

Bulk imports (the scheduled sync) only flag listings, so the feed fills in quickly and the slow
LLM work trails behind without ever running in parallel or blocking imports.
"""

import time
from collections.abc import Callable

from housing_netherlands.core.errors import LLMUnavailableError
from housing_netherlands.core.importing import ImportDeps, ensure_summary
from housing_netherlands.log import get_logger

log = get_logger(__name__)


# Two LLM failures in a row: the model is down, not just slow on one listing.
MAX_LLM_FAILURES_IN_A_ROW = 2


async def summarize_pending(
    deps: ImportDeps,
    *,
    budget_s: float,
    backoff: dict[int, float],
    retry_after_s: float = 3600.0,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Summarise flagged listings, newest first, until none are left or `budget_s` has passed
    (checked before each one). Returns how many were done.

    LLM unreachable or timed out: the listing keeps its flag and waits `retry_after_s` before
    it is tried again (`backoff`: listing id -> clock time, kept by the caller across runs), so
    one listing too long for a slow model can't block the rest; two failures in a row end the
    run. Any other failure (e.g. invalid output twice): drop the flag; the feed keeps showing
    "summary on its way" for it.
    """
    done = failures_in_a_row = 0
    deadline = clock() + budget_s
    while clock() < deadline and failures_in_a_row < MAX_LLM_FAILURES_IN_A_ROW:
        waiting = {i for i, until in backoff.items() if until > clock()}
        pending = await deps.listings.pending_summaries(limit=len(waiting) + 1)
        listing_id = next((i for i in pending if i not in waiting), None)
        if listing_id is None:
            break
        view = await deps.listings.get_view(listing_id)
        if view is None:  # deleted meanwhile; the next run picks up the rest
            break
        try:
            await ensure_summary(deps, listing_id, view.listing, now=True)
        except LLMUnavailableError as exc:
            log.warning("summary_backlog.llm_unavailable", listing_id=listing_id, error=str(exc))
            backoff[listing_id] = clock() + retry_after_s
            failures_in_a_row += 1
            continue
        except Exception as exc:
            log.error("summary_backlog.failed", listing_id=listing_id, error=repr(exc))
            await deps.listings.clear_summary_pending(listing_id)
            continue
        backoff.pop(listing_id, None)
        failures_in_a_row = 0
        done += 1
    return done
