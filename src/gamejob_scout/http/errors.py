"""Typed failures raised by the HTTP layer.

After construction, :meth:`HttpFetcher.get` raises only these. Callers never
need to import ``httpx`` to handle a failure, and every message names the URL
and the reason without ever including a response body.
"""

from gamejob_scout.errors import GameJobScoutError

__all__ = [
    "CrawlDelayTooLongError",
    "FetchError",
    "FetcherClosedError",
    "HttpStatusError",
    "InsecureRedirectError",
    "InvalidRedirectError",
    "InvalidUrlError",
    "MissingLocationError",
    "RedirectError",
    "RetryAfterTooLongError",
    "RetryExhaustedError",
    "RobotsDisallowedError",
    "RobotsError",
    "RobotsUnavailableError",
    "TooManyRedirectsError",
    "TransportFailureError",
]


class FetchError(GameJobScoutError):
    """Something went wrong fetching a URL."""

    def __init__(self, url: str, message: str) -> None:
        super().__init__(f"{message}: {url}")
        self.url = url


class InvalidUrlError(FetchError):
    """The URL is not something we are willing or able to request."""


class FetcherClosedError(FetchError):
    """The fetcher was already closed."""


class RobotsError(FetchError):
    """Base for every reason robots.txt stopped us."""


class RobotsDisallowedError(RobotsError):
    """robots.txt forbids this path for our user agent."""

    def __init__(self, url: str, user_agent: str) -> None:
        super().__init__(url, f"robots.txt disallows {user_agent!r}")
        self.user_agent = user_agent


class RobotsUnavailableError(RobotsError):
    """robots.txt could not be read, so we refuse to guess and stop."""


class CrawlDelayTooLongError(RobotsError):
    """robots.txt asks for a slower crawl than this run is willing to wait out.

    We neither ignore the site's wishes nor stall the run, so the source is
    skipped and reported instead.
    """

    def __init__(self, url: str, crawl_delay_seconds: float, maximum_seconds: float) -> None:
        super().__init__(
            url,
            f"robots.txt requests a {crawl_delay_seconds}s crawl delay, "
            f"above the configured maximum of {maximum_seconds}s",
        )
        self.crawl_delay_seconds = crawl_delay_seconds
        self.maximum_seconds = maximum_seconds


class HttpStatusError(FetchError):
    """The server answered with a status we will not retry."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(url, f"HTTP {status_code}")
        self.status_code = status_code


class RetryAfterTooLongError(FetchError):
    """The server asked us to wait longer than this run is willing to wait."""

    def __init__(self, url: str, status_code: int, retry_after_seconds: float) -> None:
        super().__init__(
            url,
            f"HTTP {status_code} with Retry-After of {retry_after_seconds}s, "
            "above the configured maximum",
        )
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class TransportFailureError(FetchError):
    """A connection-level failure: timeout, reset, protocol error."""


class RetryExhaustedError(FetchError):
    """Every attempt failed.

    ``__cause__`` is the exception describing the final attempt, so callers can
    tell a repeated 503 from a repeated timeout.
    """

    def __init__(self, url: str, attempts: int) -> None:
        super().__init__(url, f"gave up after {attempts} attempts")
        self.attempts = attempts


class RedirectError(FetchError):
    """The server redirected us somewhere we will not follow."""


class MissingLocationError(RedirectError):
    """A redirect status arrived without a usable Location header."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(url, f"HTTP {status_code} redirect without a Location header")
        self.status_code = status_code


class InvalidRedirectError(RedirectError):
    """The Location header was unparseable, or pointed at a scheme we do not use.

    Separate from :class:`InvalidUrlError`, which is about the URL the caller
    asked for rather than one a server handed back.
    """

    def __init__(self, url: str, location: str, reason: str) -> None:
        super().__init__(url, f"redirect to {location!r} rejected: {reason}")
        self.location = location


class InsecureRedirectError(RedirectError):
    """An https URL tried to redirect us down to http."""

    def __init__(self, url: str, location: str) -> None:
        super().__init__(url, f"refusing an https to http redirect to {location}")
        self.location = location


class TooManyRedirectsError(RedirectError):
    """The redirect chain was longer than we allow."""

    def __init__(self, url: str, hops: int) -> None:
        super().__init__(url, f"more than {hops} redirects")
        self.hops = hops
