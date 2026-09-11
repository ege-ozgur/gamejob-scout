"""Deciding whether to retry, and how long to wait first.

Pure functions with no HTTP and no clock of their own, so the interesting cases
can be tested directly.
"""

import random
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final

__all__ = [
    "RETRYABLE_STATUS",
    "backoff_cap",
    "backoff_delay",
    "is_retryable_status",
    "parse_retry_after",
]

RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})
"""Statuses worth trying again.

An explicit list rather than "anything 5xx": a 501 Not Implemented will not fix
itself, so hammering it is just rudeness.
"""

_MAX_EXPONENT: Final = 32
"""Guards against an enormous ``max_attempts`` overflowing the shift."""

_DELAY_SECONDS = re.compile(r"^\d+$")
"""Retry-After's delay form is a non-negative integer and nothing else.

Anchoring on this rejects "-5", "1.5", "NaN" and "inf" by construction, rather
than handing them to float() and hoping.
"""


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS


def backoff_cap(attempt: int, *, base_seconds: float, maximum_seconds: float) -> float:
    """Longest this attempt is allowed to wait, before jitter."""
    exponent = min(max(attempt - 1, 0), _MAX_EXPONENT)
    return min(maximum_seconds, base_seconds * float(2**exponent))


def backoff_delay(
    attempt: int,
    *,
    base_seconds: float,
    maximum_seconds: float,
    rng: random.Random,
) -> float:
    """Exponential backoff with full jitter.

    Full jitter (a uniform pick from zero to the cap) spreads retries out better
    than waiting the exact cap every time. ``rng`` is injected so tests can make
    the result exact.
    """
    cap = backoff_cap(attempt, base_seconds=base_seconds, maximum_seconds=maximum_seconds)
    if cap <= 0:
        return 0.0
    return rng.uniform(0.0, cap)


def parse_retry_after(raw: str, *, now: datetime) -> float | None:
    """Read a Retry-After header.

    Returns the number of seconds to wait, or ``None`` when the header cannot be
    trusted, in which case the caller falls back to exponential backoff. A date
    already in the past becomes 0.0 rather than a negative wait.
    """
    text = raw.strip()
    if not text:
        return None

    if _DELAY_SECONDS.match(text):
        return float(text)

    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None

    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)

    return max(0.0, (target - now).total_seconds())
