"""Shared HTTP fetching.

Transport policy lives here rather than under ``collectors`` because it is
cross-cutting: collectors use it today, and the ingestion runner will too.
"""

from gamejob_scout.http.backoff import (
    RETRYABLE_STATUS,
    backoff_cap,
    backoff_delay,
    is_retryable_status,
    parse_retry_after,
)
from gamejob_scout.http.config import HttpConfig
from gamejob_scout.http.errors import (
    CrawlDelayTooLongError,
    FetcherClosedError,
    FetchError,
    HttpStatusError,
    InsecureRedirectError,
    InvalidRedirectError,
    InvalidUrlError,
    MissingLocationError,
    RedirectError,
    RetryAfterTooLongError,
    RetryExhaustedError,
    RobotsDisallowedError,
    RobotsError,
    RobotsUnavailableError,
    TooManyRedirectsError,
    TransportFailureError,
)
from gamejob_scout.http.fetcher import (
    REDIRECT_STATUS,
    FetchedDocument,
    HttpFetcher,
    timeout_from_config,
)
from gamejob_scout.http.ratelimit import HostRateLimiter, normalize_host
from gamejob_scout.http.robots import (
    RobotsCache,
    RobotsPolicy,
    normalize_origin,
    parse_robots_document,
    robots_url_for,
)

__all__ = [
    "REDIRECT_STATUS",
    "RETRYABLE_STATUS",
    "CrawlDelayTooLongError",
    "FetchError",
    "FetchedDocument",
    "FetcherClosedError",
    "HostRateLimiter",
    "HttpConfig",
    "HttpFetcher",
    "HttpStatusError",
    "InsecureRedirectError",
    "InvalidRedirectError",
    "InvalidUrlError",
    "MissingLocationError",
    "RedirectError",
    "RetryAfterTooLongError",
    "RetryExhaustedError",
    "RobotsCache",
    "RobotsDisallowedError",
    "RobotsError",
    "RobotsPolicy",
    "RobotsUnavailableError",
    "TooManyRedirectsError",
    "TransportFailureError",
    "backoff_cap",
    "backoff_delay",
    "is_retryable_status",
    "normalize_host",
    "normalize_origin",
    "parse_retry_after",
    "parse_robots_document",
    "robots_url_for",
    "timeout_from_config",
]
