"""Keeping a polite distance between requests to the same host.

Not thread-safe, matching :class:`~gamejob_scout.http.fetcher.HttpFetcher`. One
limiter belongs to one fetcher on one thread.
"""

from collections.abc import Callable
from urllib.parse import urlsplit

__all__ = ["HostRateLimiter", "normalize_host"]


def normalize_host(url: str) -> str:
    """The rate-limiting key for a URL: its lowercased hostname.

    Scheme and port are deliberately ignored, so ``http://x``, ``https://x`` and
    ``https://x:8443`` share one budget. Politeness is about load on a machine,
    and the same machine usually answers all three.
    """
    hostname = urlsplit(url).hostname
    return hostname.lower() if hostname else ""


class HostRateLimiter:
    """Spaces out requests per host, and sleeps for the difference."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep
        self._next_free: dict[str, float] = {}

    def reserve(self, host: str, *, interval: float, not_before: float = 0.0) -> float:
        """Wait for this host's next slot and return the time the request starts.

        ``not_before`` is an absolute deadline from a retry schedule. Taking the
        later of the two rather than adding them is what stops a retry delay and
        a rate-limit wait from stacking up on each other.

        The following slot is reserved *before* sleeping, so a slow response
        cannot bunch up the requests that come after it.
        """
        now = self._monotonic()
        start_at = max(self._next_free.get(host, 0.0), not_before, now)
        self._next_free[host] = start_at + interval

        wait = start_at - now
        if wait > 0:
            self._sleep(wait)
        return start_at

    def bump(self, host: str, not_before: float) -> None:
        """Push a host's next slot later. Never brings it earlier.

        Used once robots.txt has been read and may have asked for a longer gap
        than the one already reserved.
        """
        self._next_free[host] = max(self._next_free.get(host, 0.0), not_before)

    def next_free(self, host: str) -> float:
        """When this host is next available. Exposed for tests and diagnostics."""
        return self._next_free.get(host, 0.0)
