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


async def summarize_pending(
    deps: ImportDeps, *, budget_s: float, clock: Callable[[], float] = time.monotonic
) -> int:
    """Summarise flagged listings, newest first, until none are left or `budget_s` has passed
    (checked before each one). Returns how many were done.

    LLM unreachable: stop and leave the flag, the next run tries again. Any other failure
    (e.g. invalid output twice): drop the flag so one bad listing can't block the backlog;
    the feed keeps showing "summary on its way" for it.
    """
    done = 0
    deadline = clock() + budget_s
    while clock() < deadline:
        pending = await deps.listings.pending_summaries(limit=1)
        if not pending:
            break
        listing_id = pending[0]
        view = await deps.listings.get_view(listing_id)
        if view is None:  # deleted meanwhile; the next run picks up the rest
            break
        try:
            await ensure_summary(deps, listing_id, view.listing, now=True)
        except LLMUnavailableError as exc:
            log.warning("summary_backlog.llm_unavailable", listing_id=listing_id, error=str(exc))
            break
        except Exception as exc:
            log.error("summary_backlog.failed", listing_id=listing_id, error=repr(exc))
            await deps.listings.clear_summary_pending(listing_id)
            continue
        done += 1
    return done
