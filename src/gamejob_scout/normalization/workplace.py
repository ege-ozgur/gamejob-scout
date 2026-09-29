"""Deciding where a job is actually done.

Resolution is a ladder with a stated answer at every rung, because the
interesting cases are the ones where the sources disagree or say something we do
not recognise.
"""

import re
from typing import Final

from gamejob_scout.domain import WorkplaceType
from gamejob_scout.normalization.locations import fold

__all__ = ["RECOGNISED_RAW", "resolve_workplace_type"]

RECOGNISED_RAW: Final[dict[str, WorkplaceType]] = {
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
    "onsite": WorkplaceType.ON_SITE,
    "on-site": WorkplaceType.ON_SITE,
    "on_site": WorkplaceType.ON_SITE,
}
"""The values Lever is known to publish, other than ``unspecified``."""

_DEFERS_TO_TEXT: Final[frozenset[str]] = frozenset({"unspecified"})
"""Raw values that explicitly say nothing, so the text may speak instead."""

_TEXT_SIGNALS: Final[tuple[tuple[WorkplaceType, tuple[str, ...]], ...]] = (
    (WorkplaceType.REMOTE, ("remote", "uzaktan", "remote-first")),
    (WorkplaceType.HYBRID, ("hybrid", "hibrit")),
    (WorkplaceType.ON_SITE, ("on-site", "onsite", "on site", "ofis", "office-based")),
)
"""Explicit words only. A city name is not in here, and that is the point."""


def _signals_in(text: str | None) -> set[WorkplaceType]:
    if not text:
        return set()
    folded = fold(text)
    found: set[WorkplaceType] = set()
    for kind, tokens in _TEXT_SIGNALS:
        if any(re.search(rf"(?<!\w){re.escape(fold(token))}(?!\w)", folded) for token in tokens):
            found.add(kind)
    return found


def resolve_workplace_type(
    *,
    raw: str | None,
    title: str,
    location_raw: str | None,
) -> WorkplaceType:
    """Work out the workplace type, or admit that we cannot.

    The ladder:

    1. A **recognised** ``raw`` value wins outright. The company stated it, so
       the text is not consulted at all.
    2. ``unspecified``, empty, or absent defers to the title and location.
    3. Any **other** non-empty ``raw`` value yields ``UNKNOWN``. It means the
       source said something we do not understand, and overriding an explicit
       statement with a guess from a job title would be presumptuous. It also
       makes a new vocabulary visible instead of quietly papering over it.

    Within step 2, the title and the location are read for explicit words only.
    If they **disagree** — a remote title beside a hybrid location — the answer
    is ``UNKNOWN``; two contradictory statements are no reason to prefer one.

    A city name is not a signal, so a remote title in İstanbul is ``REMOTE``
    rather than a conflict: that role may well be remote-from-İstanbul. The
    description is never read, because "we are not a remote company" would flip
    a job the wrong way.
    """
    if raw is not None and raw.strip():
        folded = fold(raw)
        if folded in RECOGNISED_RAW:
            return RECOGNISED_RAW[folded]
        if folded not in _DEFERS_TO_TEXT:
            return WorkplaceType.UNKNOWN

    signals = _signals_in(title) | _signals_in(location_raw)
    if len(signals) == 1:
        return signals.pop()
    return WorkplaceType.UNKNOWN
