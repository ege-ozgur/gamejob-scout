"""The fetcher end to end: retries, timing, redirects, and lifecycle.

Every timing assertion checks total elapsed fake time, not just how many sleeps
happened, because the thing worth protecting is that a retry wait and a
rate-limit wait never stack up on each other.
"""

import httpx
import pytest
import respx

from gamejob_scout.http import (
    FetcherClosedError,
    HttpFetcher,
    HttpStatusError,
    InsecureRedirectError,
    InvalidRedirectError,
    InvalidUrlError,
    MissingLocationError,
    RetryAfterTooLongError,
    RetryExhaustedError,
    TooManyRedirectsError,
    TransportFailureError,
    timeout_from_config,
)
from tests.http.conftest import (
    ALLOW_ALL,
    OTHER_ROBOTS_URL,
    OTHER_TARGET_URL,
    ROBOTS_URL,
    TARGET_URL,
    USER_AGENT,
    FakeClock,
    make_config,
    make_fetcher,
)


def allow_all(router: respx.MockRouter, url: str = ROBOTS_URL) -> respx.Route:
    return router.get(url).respond(200, text=ALLOW_ALL)


# -- success ---------------------------------------------------------------


def test_a_successful_fetch(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(200, text="hello")

    document = fetcher.get(TARGET_URL)

    assert document.status_code == 200
    assert document.text == "hello"
    assert document.url == TARGET_URL
    assert len(router.calls) == 2
    assert clock.elapsed == 1.0


def test_every_request_identifies_us(router: respx.MockRouter, fetcher: HttpFetcher) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)

    for call in router.calls:
        assert call.request.headers["user-agent"] == USER_AGENT


def test_each_timeout_is_configured_separately(clock: FakeClock) -> None:
    config = make_config()
    expected = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)

    assert timeout_from_config(config) == expected
    with make_fetcher(clock, config=config) as fetcher:
        assert fetcher._client.timeout == expected


# -- retry timing ----------------------------------------------------------


def test_a_short_backoff_hides_inside_the_host_interval(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    """A 0.4s jitter must not push the retry past the 1s host slot."""
    allow_all(router)
    router.get(TARGET_URL).mock(side_effect=[httpx.Response(429), httpx.Response(200, text="ok")])

    with make_fetcher(clock, jitter=0.4) as fetcher:
        assert fetcher.get(TARGET_URL).status_code == 200

    assert clock.sleeps == [1.0, 1.0]
    assert clock.elapsed == 2.0
    assert len(router.calls) == 3


def test_a_retry_after_longer_than_the_interval_wins(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(200, text="ok"),
        ],
    )

    assert fetcher.get(TARGET_URL).status_code == 200
    assert clock.sleeps == [1.0, 5.0]
    assert clock.elapsed == 6.0


def test_retry_after_as_an_http_date(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "Fri, 11 Sep 2026 08:00:04 GMT"}),
            httpx.Response(200, text="ok"),
        ],
    )

    assert fetcher.get(TARGET_URL).status_code == 200
    assert clock.elapsed == 4.0


def test_a_retry_after_beyond_the_cap_ends_the_attempt(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(429, headers={"Retry-After": "3600"})

    with pytest.raises(RetryAfterTooLongError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.retry_after_seconds == 3600.0
    assert len(router.calls) == 2
    assert clock.elapsed == 1.0


def test_a_server_error_is_retried(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, text="ok")])

    assert fetcher.get(TARGET_URL).status_code == 200
    assert clock.elapsed == 2.0


def test_a_timeout_is_retried(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).mock(
        side_effect=[httpx.ReadTimeout("too slow"), httpx.Response(200, text="ok")],
    )

    assert fetcher.get(TARGET_URL).status_code == 200
    assert clock.sleeps == [1.0, 1.0]
    assert clock.elapsed == 2.0


@pytest.mark.parametrize("status", [404, 403, 400, 410, 422, 501])
def test_a_permanent_status_is_not_retried(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    status: int,
) -> None:
    allow_all(router)
    target = router.get(TARGET_URL).respond(status)

    with pytest.raises(HttpStatusError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.status_code == status
    assert target.call_count == 1


def test_running_out_of_attempts_reports_the_final_status(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(503)

    with pytest.raises(RetryExhaustedError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.attempts == 3
    cause = caught.value.__cause__
    assert isinstance(cause, HttpStatusError)
    assert cause.status_code == 503
    assert len(router.calls) == 4
    assert clock.sleeps == [1.0, 1.0, 2.0]
    assert clock.elapsed == 4.0


def test_running_out_of_attempts_reports_a_transport_failure(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).mock(side_effect=httpx.ConnectTimeout("no answer"))

    with pytest.raises(RetryExhaustedError) as caught:
        fetcher.get(TARGET_URL)

    assert isinstance(caught.value.__cause__, TransportFailureError)


def test_a_failure_after_the_bytes_arrive_is_still_a_transport_failure(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    """A DecodingError is a RequestError but not a TransportError.

    It happens once the response body is in hand and the declared encoding
    turns out to be wrong, which still means we did not get a usable page.
    """
    allow_all(router)
    router.get(TARGET_URL).mock(side_effect=httpx.DecodingError("bad gzip"))

    with pytest.raises(RetryExhaustedError) as caught:
        fetcher.get(TARGET_URL)

    cause = caught.value.__cause__
    assert isinstance(cause, TransportFailureError)
    assert "DecodingError" in str(cause)
    assert caught.value.attempts == 3
    assert len(router.calls) == 4


# -- status classification -------------------------------------------------


@pytest.mark.parametrize("status", [101, 300, 304, 305, 306, 399])
def test_a_status_we_cannot_act_on_is_reported_not_returned(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    status: int,
) -> None:
    """Anything below 400 that is not a 2xx or a followable redirect.

    Returning one of these as if it were the page would hand a collector an
    empty body and no indication that anything was wrong.
    """
    allow_all(router)
    target = router.get(TARGET_URL).respond(status)

    with pytest.raises(HttpStatusError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.status_code == status
    assert target.call_count == 1


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_every_success_status_is_returned(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    status: int,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(status)

    assert fetcher.get(TARGET_URL).status_code == status


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_followable_redirect_is_followed(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    status: int,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(status, headers={"Location": "/openings"})
    router.get("https://example.com/openings").respond(200, text="ok")

    assert fetcher.get(TARGET_URL).url == "https://example.com/openings"


# -- rate limiting ---------------------------------------------------------


def test_two_fetches_from_one_host_are_spaced_out(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)
    fetcher.get(TARGET_URL)

    assert clock.sleeps == [1.0, 1.0]
    assert len(router.calls) == 3


def test_a_second_host_does_not_queue_behind_the_first(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    """The second host waits only behind its own robots request."""
    allow_all(router)
    allow_all(router, OTHER_ROBOTS_URL)
    router.get(TARGET_URL).respond(200, text="ok")
    router.get(OTHER_TARGET_URL).respond(200, text="ok")

    fetcher.get(TARGET_URL)
    fetcher.get(OTHER_TARGET_URL)

    assert clock.sleeps == [1.0, 1.0]
    assert clock.elapsed == 2.0
    assert len(router.calls) == 4


# -- redirects -------------------------------------------------------------


def test_a_relative_redirect_is_resolved(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": "/openings"})
    router.get("https://example.com/openings").respond(200, text="ok")

    document = fetcher.get(TARGET_URL)

    assert document.url == "https://example.com/openings"
    assert len(router.calls) == 3


def test_a_redirect_to_another_host_is_checked_against_its_own_robots(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    allow_all(router)
    other_robots = allow_all(router, OTHER_ROBOTS_URL)
    router.get(TARGET_URL).respond(302, headers={"Location": OTHER_TARGET_URL})
    router.get(OTHER_TARGET_URL).respond(200, text="ok")

    document = fetcher.get(TARGET_URL)

    assert document.url == OTHER_TARGET_URL
    assert other_robots.called
    assert len(router.calls) == 4
    assert clock.elapsed == 2.0


def test_a_redirect_without_a_location_header(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(302)

    with pytest.raises(MissingLocationError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.status_code == 302


def test_an_unparseable_location(router: respx.MockRouter, fetcher: HttpFetcher) -> None:
    """An unclosed IPv6 bracket is one of the few things urljoin truly rejects."""
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": "http://["})

    with pytest.raises(InvalidRedirectError, match="could not be parsed"):
        fetcher.get(TARGET_URL)


def test_a_location_that_only_looks_like_a_scheme_is_treated_as_a_path(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    """`ht!tp:` is not a valid scheme, so urljoin reads it as a relative path."""
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": "ht!tp://example.com/x"})
    router.get("https://example.com/ht!tp:/example.com/x").respond(200, text="ok")

    assert fetcher.get(TARGET_URL).status_code == 200


def test_a_redirect_to_another_scheme_is_refused(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": "ftp://example.com/jobs"})

    with pytest.raises(InvalidRedirectError, match="unsupported scheme"):
        fetcher.get(TARGET_URL)


def test_a_downgrade_to_http_is_refused(router: respx.MockRouter, fetcher: HttpFetcher) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": "http://example.com/jobs"})

    with pytest.raises(InsecureRedirectError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.location == "http://example.com/jobs"


def test_a_redirect_loop_is_bounded(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": TARGET_URL})

    with pytest.raises(TooManyRedirectsError) as caught:
        fetcher.get(TARGET_URL)

    assert caught.value.hops == 5
    assert len(router.calls) == 7  # one robots read plus six target attempts


# -- bad input and lifecycle ----------------------------------------------


@pytest.mark.parametrize("url", ["ftp://example.com/jobs", "mailto:jobs@example.com", "not-a-url"])
def test_an_unusable_url_is_rejected_before_anything_is_requested(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
    url: str,
) -> None:
    with pytest.raises(InvalidUrlError):
        fetcher.get(url)

    assert len(router.calls) == 0
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:notaport/jobs",
        "https://example.com:99999/jobs",
        "https://example.com:-1/jobs",
    ],
)
def test_a_bad_port_is_caught_rather_than_escaping_as_a_value_error(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    url: str,
) -> None:
    """urlsplit tolerates a bad port until .port is read, so we read it."""
    with pytest.raises(InvalidUrlError, match="could not be parsed"):
        fetcher.get(url)

    assert len(router.calls) == 0


@pytest.mark.parametrize(
    "location",
    [
        "https://example.com:notaport/jobs",
        "https://example.com:99999/jobs",
    ],
)
def test_a_bad_port_in_a_redirect_is_caught_too(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    location: str,
) -> None:
    allow_all(router)
    router.get(TARGET_URL).respond(302, headers={"Location": location})

    with pytest.raises(InvalidRedirectError):
        fetcher.get(TARGET_URL)


def test_httpx_rejecting_a_location_header_is_not_retried(
    router: respx.MockRouter,
    fetcher: HttpFetcher,
    clock: FakeClock,
) -> None:
    """Pins a deliberate coupling to httpx's own Location validation.

    httpx parses the Location header even with follow_redirects disabled, and
    reports a non-numeric port as a RemoteProtocolError, which would otherwise
    look retryable. If httpx ever rewords that error, this test fails rather
    than the fetcher quietly going back to retrying a permanent fault.
    """
    allow_all(router)
    target = router.get(TARGET_URL).respond(
        302,
        headers={"Location": "https://example.com:notaport/jobs"},
    )

    with pytest.raises(InvalidRedirectError):
        fetcher.get(TARGET_URL)

    assert target.call_count == 1
    assert clock.sleeps == [1.0]


def test_using_a_closed_fetcher_raises_our_own_error(clock: FakeClock) -> None:
    fetcher = make_fetcher(clock)
    fetcher.close()

    with pytest.raises(FetcherClosedError):
        fetcher.get(TARGET_URL)


def test_closing_twice_is_harmless(clock: FakeClock) -> None:
    fetcher = make_fetcher(clock)
    fetcher.close()
    fetcher.close()

    assert fetcher._client.is_closed


def test_the_context_manager_closes_the_client(clock: FakeClock) -> None:
    with make_fetcher(clock) as fetcher:
        assert not fetcher._client.is_closed

    assert fetcher._client.is_closed
