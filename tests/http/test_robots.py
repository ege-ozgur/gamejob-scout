"""robots.txt: how it is read, what it means, and how it is remembered."""

import httpx
import pytest
import respx

from gamejob_scout.http import (
    CrawlDelayTooLongError,
    HttpFetcher,
    RobotsDisallowedError,
    RobotsUnavailableError,
    normalize_origin,
)
from tests.http.conftest import (
    ALLOW_ALL,
    DISALLOW_ALL,
    ROBOTS_URL,
    TARGET_URL,
    USER_AGENT,
    FakeClock,
    robots_with_crawl_delay,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/jobs", "https://example.com"),
        ("https://EXAMPLE.com/jobs", "https://example.com"),
        ("https://example.com:443/jobs", "https://example.com"),
        ("http://example.com:80/jobs", "http://example.com"),
        ("https://example.com:8443/jobs", "https://example.com:8443"),
        ("http://example.com/jobs", "http://example.com"),
    ],
)
def test_origins_are_normalized_per_scheme_and_port(url: str, expected: str) -> None:
    """Finer-grained than the rate-limit key: robots.txt is defined per origin."""
    assert normalize_origin(url) == expected


def test_an_allowed_path_is_fetched(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(TARGET_URL).respond(200, text="ok")

    assert fetcher.get(TARGET_URL).status_code == 200
    assert len(router.calls) == 2
    assert clock.elapsed == 1.0


def test_a_disallowed_path_is_never_requested(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=DISALLOW_ALL)
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsDisallowedError):
        fetcher.get(TARGET_URL)

    assert not target.called
    assert len(router.calls) == 1
    assert clock.sleeps == []


def test_robots_is_read_once_per_origin(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    robots = router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)
    fetcher.get(TARGET_URL)

    assert robots.call_count == 1
    assert len(router.calls) == 3


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_a_client_error_means_there_are_no_rules(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    status: int,
) -> None:
    router.get(ROBOTS_URL).respond(status)
    router.get(TARGET_URL).respond(200, text="ok")

    assert fetcher.get(TARGET_URL).status_code == 200


@pytest.mark.parametrize("status", [501, 505])
def test_an_unexpected_server_error_fails_closed_at_once(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    status: int,
) -> None:
    router.get(ROBOTS_URL).respond(status)
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsUnavailableError):
        fetcher.get(TARGET_URL)

    assert not target.called
    assert len(router.calls) == 1


def test_a_retryable_status_is_retried_then_fails_closed(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(429)
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsUnavailableError):
        fetcher.get(TARGET_URL)

    assert len(router.calls) == 3
    assert clock.sleeps == [1.0, 2.0]
    assert not target.called


def test_a_transport_failure_fails_closed(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    router.get(ROBOTS_URL).mock(side_effect=httpx.ConnectError("no route"))
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsUnavailableError):
        fetcher.get(TARGET_URL)

    assert len(router.calls) == 3
    assert not target.called


def test_an_unavailable_verdict_is_remembered(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    """A broken robots.txt costs one failed read per run, not one per URL."""
    robots = router.get(ROBOTS_URL).respond(501)

    for _ in range(2):
        with pytest.raises(RobotsUnavailableError):
            fetcher.get(TARGET_URL)

    assert robots.call_count == 1


def test_retry_after_beyond_the_cap_fails_closed(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    router.get(ROBOTS_URL).respond(429, headers={"Retry-After": "3600"})
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsUnavailableError):
        fetcher.get(TARGET_URL)

    assert not target.called


def test_crawl_delay_holds_back_the_first_request(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    """The delay applies immediately, not from the second request onwards."""
    router.get(ROBOTS_URL).respond(200, text=robots_with_crawl_delay(5))
    router.get(TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)

    assert clock.sleeps == [5.0]
    assert clock.elapsed == 5.0


def test_crawl_delay_is_anchored_to_the_request_that_actually_answered(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    """A failed first read must not let the target start early.

    robots.txt fails at t=0 and succeeds at t=1. The five second delay counts
    from t=1, so the target starts at t=6 rather than t=5.
    """
    router.get(ROBOTS_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, text=robots_with_crawl_delay(5)),
        ],
    )
    router.get(TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)

    assert clock.sleeps == [1.0, 5.0]
    assert clock.elapsed == 6.0


def test_a_crawl_delay_exactly_at_the_cap_is_honoured(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=robots_with_crawl_delay(60))
    router.get(TARGET_URL).respond(200, text="ok")

    assert fetcher.get(TARGET_URL).status_code == 200
    assert clock.sleeps == [60.0]


def test_a_crawl_delay_above_the_cap_stops_the_source(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    """We neither ignore the site's wishes nor sit out an unreasonable wait."""
    router.get(ROBOTS_URL).respond(200, text=robots_with_crawl_delay(61))
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(CrawlDelayTooLongError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.crawl_delay_seconds == 61.0
    assert caught.value.maximum_seconds == 60.0
    assert not target.called
    assert clock.sleeps == []


def test_a_robots_redirect_is_followed_without_another_robots_check(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    """Gating a robots fetch on robots would never terminate."""
    router.get(ROBOTS_URL).respond(302, headers={"Location": "https://cdn.example/policy.txt"})
    router.get("https://cdn.example/policy.txt").respond(200, text=ALLOW_ALL)
    cdn_robots = router.get("https://cdn.example/robots.txt").respond(200, text=ALLOW_ALL)
    router.get(TARGET_URL).respond(200, text="ok")

    assert fetcher.get(TARGET_URL).status_code == 200
    assert not cdn_robots.called


def test_a_robots_redirect_may_not_downgrade_to_http(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    router.get(ROBOTS_URL).respond(302, headers={"Location": "http://example.com/robots.txt"})
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsUnavailableError):
        fetcher.get(TARGET_URL)

    assert not target.called


def test_a_long_robots_redirect_chain_runs_out_of_budget(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    router.get(ROBOTS_URL).respond(302, headers={"Location": "/r1"})
    router.get("https://example.com/r1").respond(302, headers={"Location": "/r2"})
    router.get("https://example.com/r2").respond(302, headers={"Location": "/r3"})
    target = router.get(TARGET_URL).respond(200, text="ok")

    with pytest.raises(RobotsUnavailableError):
        fetcher.get(TARGET_URL)

    assert len(router.calls) == 3
    assert not target.called


def test_the_robots_request_uses_the_configured_user_agent(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)

    assert [call.request.headers["user-agent"] for call in router.calls] == [USER_AGENT] * 2
