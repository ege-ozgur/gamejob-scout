"""Per-host spacing, and the rule that keeps waits from stacking up."""

import pytest

from gamejob_scout.http import HostRateLimiter, normalize_host
from tests.http.conftest import FakeClock


def make_limiter(clock: FakeClock) -> HostRateLimiter:
    return HostRateLimiter(monotonic=clock.monotonic, sleep=clock.sleep)


def test_the_first_request_to_a_host_waits_for_nothing(clock: FakeClock) -> None:
    start = make_limiter(clock).reserve("example.com", interval=1.0)

    assert start == 0.0
    assert clock.sleeps == []


def test_the_second_request_waits_a_full_interval(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.reserve("example.com", interval=1.0)
    start = limiter.reserve("example.com", interval=1.0)

    assert start == 1.0
    assert clock.sleeps == [1.0]
    assert clock.elapsed == 1.0


def test_each_host_keeps_its_own_budget(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.reserve("example.com", interval=1.0)
    limiter.reserve("other.example", interval=1.0)

    assert clock.sleeps == []


def test_a_short_retry_delay_hides_inside_the_host_interval(clock: FakeClock) -> None:
    """The wait is max(host slot, retry deadline), never the sum of the two."""
    limiter = make_limiter(clock)
    limiter.reserve("example.com", interval=1.0)

    start = limiter.reserve("example.com", interval=1.0, not_before=0.4)

    assert start == 1.0
    assert clock.elapsed == 1.0


def test_a_long_retry_delay_wins(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.reserve("example.com", interval=1.0)

    start = limiter.reserve("example.com", interval=1.0, not_before=6.0)

    assert start == 6.0
    assert clock.elapsed == 6.0


def test_bump_pushes_the_next_slot_later(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.reserve("example.com", interval=1.0)
    limiter.bump("example.com", 5.0)

    start = limiter.reserve("example.com", interval=1.0)

    assert start == 5.0
    assert clock.sleeps == [5.0]


def test_bump_never_pulls_a_slot_earlier(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.reserve("example.com", interval=10.0)
    limiter.bump("example.com", 2.0)

    assert limiter.next_free("example.com") == 10.0


def test_the_slot_is_reserved_before_sleeping(clock: FakeClock) -> None:
    """Three requests queue up in order rather than bunching together."""
    limiter = make_limiter(clock)
    starts = [limiter.reserve("example.com", interval=1.0) for _ in range(3)]

    assert starts == [0.0, 1.0, 2.0]
    assert clock.elapsed == 2.0


@pytest.mark.parametrize(
    "url",
    ["http://example.com/a", "https://example.com/b", "https://EXAMPLE.com:8443/c"],
)
def test_scheme_and_port_share_one_budget(url: str) -> None:
    """One machine answers all of these, so one budget is the polite reading."""
    assert normalize_host(url) == "example.com"


def test_a_url_without_a_host_normalizes_to_nothing() -> None:
    assert normalize_host("not-a-url") == ""
