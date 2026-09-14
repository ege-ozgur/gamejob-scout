"""Settings for the HTTP layer, validated at construction.

Every value is checked here rather than where it is used, so a bad setting fails
immediately and names the field, instead of producing a confusing timeout or an
accidental infinite wait much later.
"""

import math
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["HttpConfig"]

_URL_IN_TEXT = re.compile(r"https?://[^\s)\]>,]+")


def _reject_bool(name: str, value: object) -> None:
    """Booleans are integers in Python, so they must be excluded explicitly.

    Without this, ``max_attempts=True`` would quietly mean "one attempt".
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not a bool")


def _as_finite_number(name: str, value: float) -> float:
    _reject_bool(name, value)
    if not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _check_positive(name: str, value: float) -> None:
    if _as_finite_number(name, value) <= 0:
        raise ValueError(f"{name} must be greater than 0")


def _check_non_negative(name: str, value: float) -> None:
    if _as_finite_number(name, value) < 0:
        raise ValueError(f"{name} must not be negative")


def _check_int_at_least(name: str, value: int, minimum: int) -> None:
    _reject_bool(name, value)
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")


def _check_user_agent(value: str) -> None:
    """Require an honest, contactable identifier.

    Sites that want to know who is crawling them should be able to find out, so
    the user agent has to carry a real http(s) URL. This is enforced in code
    rather than asked for in a comment.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("user_agent must not be blank")

    match = _URL_IN_TEXT.search(value)
    if match is None:
        raise ValueError("user_agent must contain an absolute http(s) project or contact URL")

    parts = urlsplit(match.group(0))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("user_agent must contain an absolute http(s) project or contact URL")


@dataclass(frozen=True, slots=True)
class HttpConfig:
    """How the fetcher talks to the outside world.

    ``max_attempts`` counts *total* attempts including the first, so the default
    of 3 means one request plus two retries, and therefore two backoff waits.
    """

    user_agent: str

    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    write_timeout: float = 10.0
    pool_timeout: float = 5.0

    requests_per_second: float = 1.0

    max_attempts: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    max_retry_after_seconds: float = 60.0
    max_crawl_delay_seconds: float = 60.0

    max_redirects: int = 5

    def __post_init__(self) -> None:
        _check_user_agent(self.user_agent)

        for name in ("connect_timeout", "read_timeout", "write_timeout", "pool_timeout"):
            _check_positive(name, getattr(self, name))

        _check_positive("requests_per_second", self.requests_per_second)
        _check_int_at_least("max_attempts", self.max_attempts, 1)
        _check_non_negative("base_backoff_seconds", self.base_backoff_seconds)
        _check_non_negative("max_backoff_seconds", self.max_backoff_seconds)
        _check_non_negative("max_retry_after_seconds", self.max_retry_after_seconds)
        _check_non_negative("max_crawl_delay_seconds", self.max_crawl_delay_seconds)
        _check_int_at_least("max_redirects", self.max_redirects, 0)

        if self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("max_backoff_seconds must be at least base_backoff_seconds")

    @property
    def base_interval_seconds(self) -> float:
        """Minimum gap between two requests to the same host."""
        return 1.0 / self.requests_per_second
