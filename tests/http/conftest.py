"""Test seams for the HTTP layer.

Nothing here touches the network or the real clock. The fake clock is the
important piece: sleeping advances the same monotonic counter the rate limiter
and the retry scheduler read, so a test can assert *total elapsed time* rather
than merely counting sleep calls.
"""

import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from gamejob_scout.http import HttpConfig, HttpFetcher

_SSL_CONTEXT = httpx.create_ssl_context()
"""Built once for the whole session.

Loading the system trust store costs roughly half a second per client on
Windows, which would otherwise dominate the runtime of a suite that never opens
a socket. Sharing it is purely a speed fix: respx still intercepts every
request, and production code is untouched.
"""

USER_AGENT = "gamejob-scout-tests/0.1 (+https://example.com/gamejob-scout)"

ORIGIN = "https://example.com"
ROBOTS_URL = f"{ORIGIN}/robots.txt"
TARGET_URL = f"{ORIGIN}/jobs"

OTHER_ORIGIN = "https://other.example"
OTHER_ROBOTS_URL = f"{OTHER_ORIGIN}/robots.txt"
OTHER_TARGET_URL = f"{OTHER_ORIGIN}/jobs"

ALLOW_ALL = "User-agent: *\nDisallow:\n"
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


def robots_with_crawl_delay(seconds: int) -> str:
    return f"User-agent: *\nCrawl-delay: {seconds}\nDisallow:\n"


class FakeClock:
    """A monotonic clock, a wall clock, and a sleeper that moves both."""

    def __init__(self, wall: datetime | None = None) -> None:
        self._monotonic = 0.0
        self._wall = wall if wall is not None else datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._monotonic

    def now(self) -> datetime:
        return self._wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._monotonic += seconds
        self._wall += timedelta(seconds=seconds)

    @property
    def elapsed(self) -> float:
        return self._monotonic


class FixedJitter(random.Random):
    """A Random whose uniform() always lands at the same point in the range.

    ``fraction=1.0`` makes every backoff equal its cap, which turns the jitter
    into something a test can state exactly.
    """

    def __init__(self, fraction: float = 1.0) -> None:
        super().__init__(0)
        self._fraction = fraction

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self._fraction


def make_config(**overrides: Any) -> HttpConfig:
    defaults: dict[str, Any] = {"user_agent": USER_AGENT}
    return HttpConfig(**{**defaults, **overrides})


def make_fetcher(
    clock: FakeClock,
    *,
    config: HttpConfig | None = None,
    jitter: float = 1.0,
) -> HttpFetcher:
    return HttpFetcher(
        config if config is not None else make_config(),
        transport=httpx.HTTPTransport(verify=_SSL_CONTEXT),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=clock.now,
        rng=FixedJitter(jitter),
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def fetcher(clock: FakeClock) -> Iterator[HttpFetcher]:
    with make_fetcher(clock) as instance:
        yield instance
