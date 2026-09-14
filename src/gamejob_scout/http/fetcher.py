"""The one place this project talks to the internet.

:class:`HttpFetcher` owns every transport concern so that collectors do not have
to think about any of it: timeouts, polite spacing between requests, robots.txt,
bounded retries, and redirects that are followed by hand so each hop can be
checked before it is taken.

Only GET is offered. Retrying is safe precisely because GET is idempotent; a
method that changes something on the server would need a separate entry point
with retries switched off by default.

**Not thread-safe.** One fetcher belongs to one thread. Running sources in
parallel would need a shared scheduler so that separate workers cannot each
spend the same host's request budget; that design does not exist yet, and making
a second fetcher does not provide it.
"""

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urljoin, urlsplit

import httpx

from gamejob_scout.http.backoff import backoff_delay, is_retryable_status, parse_retry_after
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
from gamejob_scout.http.ratelimit import HostRateLimiter, normalize_host
from gamejob_scout.http.robots import (
    RobotsCache,
    RobotsPolicy,
    normalize_origin,
    parse_robots_document,
    robots_url_for,
)

__all__ = ["FetchedDocument", "HttpFetcher", "timeout_from_config"]

REDIRECT_STATUS: Final[frozenset[int]] = frozenset({301, 302, 303, 307, 308})
SUPPORTED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def timeout_from_config(config: HttpConfig) -> httpx.Timeout:
    """Four separate limits rather than one, so a slow phase is identifiable."""
    return httpx.Timeout(
        connect=config.connect_timeout,
        read=config.read_timeout,
        write=config.write_timeout,
        pool=config.pool_timeout,
    )


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """A successful response, with no ``httpx`` types left in it.

    Collectors therefore never import ``httpx``, and a collector test can build
    one of these in a line instead of standing up a mock transport.
    """

    url: str
    status_code: int
    headers: Mapping[str, str]
    text: str


class HttpFetcher:
    """Fetches public pages politely, and fails in ways a caller can act on."""

    def __init__(
        self,
        config: HttpConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
        rng: random.Random | None = None,
    ) -> None:
        self._config = config
        self._monotonic = monotonic
        self._now = now
        self._rng = random.Random() if rng is None else rng
        self._limiter = HostRateLimiter(monotonic=monotonic, sleep=sleep)
        self._robots = RobotsCache()
        self._closed = False
        self._client = httpx.Client(
            timeout=timeout_from_config(config),
            follow_redirects=False,
            headers={"User-Agent": config.user_agent},
            transport=transport,
            event_hooks={"response": [self._reject_unusable_redirect]},
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the underlying client. Safe to call more than once."""
        if not self._closed:
            self._closed = True
            self._client.close()

    def __enter__(self) -> "HttpFetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- public API --------------------------------------------------------

    def get(self, url: str) -> FetchedDocument:
        """Fetch a URL, honouring robots.txt, rate limits and bounded retries.

        Raises only :class:`~gamejob_scout.http.errors.FetchError` subclasses.
        """
        if self._closed:
            raise FetcherClosedError(url, "fetcher is closed")

        current = self._checked_entry_url(url)

        for _ in range(self._config.max_redirects + 1):
            policy = self._robots_policy(current)
            if not policy.can_fetch(self._config.user_agent, current):
                raise RobotsDisallowedError(current, self._config.user_agent)

            interval = self._interval_for(policy)
            response = self._request_with_retries(current, interval=interval)

            if response.status_code in REDIRECT_STATUS:
                current = self._redirect_target(current, response)
                continue

            return FetchedDocument(
                url=current,
                status_code=response.status_code,
                headers=dict(response.headers),
                text=response.text,
            )

        raise TooManyRedirectsError(url, hops=self._config.max_redirects)

    # -- requesting --------------------------------------------------------

    def _reject_unusable_redirect(self, response: httpx.Response) -> None:
        """Check a redirect before httpx reads the Location header itself.

        httpx builds its own redirect request even when told not to follow
        redirects, and a malformed Location makes it raise a protocol error that
        looks retryable. Response hooks run first, so validating here means an
        unusable redirect is reported as the permanent redirect fault it is.

        This only validates. A redirect that passes is resolved again later when
        it is actually followed, which costs nothing worth avoiding.
        """
        if response.status_code in REDIRECT_STATUS:
            self._redirect_target(str(response.request.url), response)

    def _send(self, url: str) -> httpx.Response:
        """Issue one request, translating httpx failures into our own types.

        Only the specific httpx failures we understand are caught; anything else
        is a bug in this project and should surface as one.
        """
        try:
            return self._client.get(url)
        except httpx.UnsupportedProtocol as exc:
            raise InvalidUrlError(url, "unsupported URL scheme") from exc
        except httpx.InvalidURL as exc:
            raise InvalidUrlError(url, "malformed URL") from exc
        except httpx.RequestError as exc:
            # RequestError rather than TransportError: it also covers failures
            # such as DecodingError, which happen after the bytes arrive but
            # still mean we did not get a usable response.
            raise TransportFailureError(url, f"{type(exc).__name__}: {exc}") from exc

    def _request_with_retries(self, url: str, *, interval: float) -> httpx.Response:
        """Attempt a request until it succeeds, fails permanently, or runs out.

        The retry wait and the host's own spacing are combined as one absolute
        deadline rather than added together, so a short backoff hides inside the
        rate-limit gap instead of extending it.
        """
        host = normalize_host(url)
        not_before = 0.0
        attempt = 1
        last_error: FetchError | None = None

        while True:
            self._limiter.reserve(host, interval=interval, not_before=not_before)
            delay: float | None = None

            try:
                response = self._send(url)
            except TransportFailureError as exc:
                last_error = exc
            else:
                status = response.status_code
                # Only successes and the redirects we know how to follow are
                # handed back. A 300 or 304 is not something this fetcher can
                # act on, so it is reported rather than silently returned as if
                # it carried the page we asked for.
                if 200 <= status < 300 or status in REDIRECT_STATUS:
                    return response
                if not is_retryable_status(status):
                    raise HttpStatusError(url, status)
                delay = self._retry_after_seconds(url, response)
                last_error = HttpStatusError(url, status)

            if attempt >= self._config.max_attempts:
                raise RetryExhaustedError(url, attempts=attempt) from last_error

            if delay is None:
                delay = self._backoff(attempt)
            not_before = self._monotonic() + delay
            attempt += 1

    def _backoff(self, attempt: int) -> float:
        return backoff_delay(
            attempt,
            base_seconds=self._config.base_backoff_seconds,
            maximum_seconds=self._config.max_backoff_seconds,
            rng=self._rng,
        )

    def _retry_after_seconds(self, url: str, response: httpx.Response) -> float | None:
        """Read Retry-After, or return None so the caller falls back to backoff."""
        raw: str | None = response.headers.get("Retry-After")
        if raw is None:
            return None

        seconds = parse_retry_after(raw, now=self._now())
        if seconds is None:
            return None
        if seconds > self._config.max_retry_after_seconds:
            raise RetryAfterTooLongError(url, response.status_code, seconds)
        return seconds

    # -- redirects ---------------------------------------------------------

    def _checked_entry_url(self, url: str) -> str:
        try:
            parts = urlsplit(url)
            # urlsplit accepts a bad port and only complains when .port is
            # read, so force that here rather than letting a raw ValueError
            # surface from somewhere deeper.
            _ = parts.port
        except ValueError as exc:
            raise InvalidUrlError(url, f"URL could not be parsed: {exc}") from exc

        if parts.scheme.lower() not in SUPPORTED_SCHEMES:
            raise InvalidUrlError(url, f"unsupported URL scheme {parts.scheme!r}")
        if not parts.hostname:
            raise InvalidUrlError(url, "URL has no host")
        return url

    def _redirect_target(self, current: str, response: httpx.Response) -> str:
        """Work out where a redirect points, refusing anything unsafe.

        Redirects are resolved here rather than by httpx so that every hop goes
        back through the robots check before it is requested.
        """
        # httpx types header lookups as Any, so state what we actually expect.
        location: str | None = response.headers.get("Location")
        if location is None or not location.strip():
            raise MissingLocationError(current, response.status_code)

        raw = location.strip()
        try:
            target = urljoin(current, raw)
            parts = urlsplit(target)
            _ = parts.port  # an invalid port only surfaces when it is read
        except ValueError as exc:
            raise InvalidRedirectError(
                current,
                raw,
                f"the URL could not be parsed: {exc}",
            ) from exc

        scheme = parts.scheme.lower()
        if scheme not in SUPPORTED_SCHEMES:
            raise InvalidRedirectError(current, target, f"unsupported scheme {parts.scheme!r}")
        if not parts.hostname:
            raise InvalidRedirectError(current, target, "no host")
        if urlsplit(current).scheme.lower() == "https" and scheme == "http":
            raise InsecureRedirectError(current, target)

        return target

    # -- robots ------------------------------------------------------------

    def _interval_for(self, policy: RobotsPolicy) -> float:
        return max(self._config.base_interval_seconds, policy.crawl_delay or 0.0)

    def _robots_policy(self, url: str) -> RobotsPolicy:
        """Return the cached policy for this origin, fetching it if needed."""
        origin = normalize_origin(url)
        cached = self._robots.get(origin)
        if isinstance(cached, RobotsError):
            raise cached
        if cached is not None:
            return cached

        try:
            policy = self._fetch_robots_policy(origin)
        except RobotsError as error:
            self._robots.store(origin, error)
            raise

        self._robots.store(origin, policy)
        return policy

    def _fetch_robots_policy(self, origin: str) -> RobotsPolicy:
        """Read one origin's robots.txt, failing closed if we cannot.

        The whole read shares a single request budget of ``max_attempts``, with
        redirects counting against it, so a misconfigured site cannot turn one
        page fetch into an endless chase. Redirects here never re-enter the
        robots check, which would recurse forever.
        """
        origin_host = normalize_host(origin)
        url = robots_url_for(origin)
        interval = self._config.base_interval_seconds

        budget = self._config.max_attempts
        retries = 0
        not_before = 0.0
        last_start_on_origin: float | None = None

        while True:
            if budget <= 0:
                raise RobotsUnavailableError(url, "ran out of requests reading robots.txt")

            host = normalize_host(url)
            start_at = self._limiter.reserve(host, interval=interval, not_before=not_before)
            if host == origin_host:
                last_start_on_origin = start_at
            budget -= 1
            not_before = 0.0

            try:
                response = self._send(url)
            except InvalidUrlError as exc:
                raise RobotsUnavailableError(url, "robots.txt URL is not usable") from exc
            except RedirectError as exc:
                # Keeps the promise that reading robots.txt only ever fails as
                # a RobotsError, whatever the underlying reason was.
                raise RobotsUnavailableError(url, "robots.txt redirect was refused") from exc
            except TransportFailureError as exc:
                if budget <= 0:
                    raise RobotsUnavailableError(url, "robots.txt could not be reached") from exc
                retries += 1
                not_before = self._monotonic() + self._backoff(retries)
                continue

            status = response.status_code

            if status in REDIRECT_STATUS:
                url = self._robots_redirect_target(url, response)
                continue

            if 200 <= status < 300:
                policy = self._policy_from_document(url, response.text)
                self._space_out_first_request(origin_host, policy, last_start_on_origin)
                return policy

            if is_retryable_status(status):
                if budget <= 0:
                    raise RobotsUnavailableError(
                        url,
                        f"robots.txt kept returning HTTP {status}",
                    )
                retries += 1
                not_before = self._monotonic() + self._robots_retry_delay(url, response, retries)
                continue

            if 400 <= status < 500:
                # By convention a client error means "there are no rules here".
                policy = RobotsPolicy.allowing_everything()
                self._space_out_first_request(origin_host, policy, last_start_on_origin)
                return policy

            raise RobotsUnavailableError(url, f"robots.txt returned HTTP {status}")

    def _robots_redirect_target(self, url: str, response: httpx.Response) -> str:
        try:
            return self._redirect_target(url, response)
        except RedirectError as exc:
            raise RobotsUnavailableError(url, "robots.txt redirect was refused") from exc

    def _robots_retry_delay(self, url: str, response: httpx.Response, attempt: int) -> float:
        """Delay before the next robots attempt, failing closed if asked to wait too long."""
        try:
            delay = self._retry_after_seconds(url, response)
        except RetryAfterTooLongError as exc:
            raise RobotsUnavailableError(url, "robots.txt asked us to wait too long") from exc
        return self._backoff(attempt) if delay is None else delay

    def _policy_from_document(self, url: str, text: str) -> RobotsPolicy:
        parser = parse_robots_document(text)
        raw_delay = parser.crawl_delay(self._config.user_agent)
        crawl_delay = None if raw_delay is None else float(raw_delay)

        if crawl_delay is not None and crawl_delay > self._config.max_crawl_delay_seconds:
            raise CrawlDelayTooLongError(url, crawl_delay, self._config.max_crawl_delay_seconds)

        return RobotsPolicy(allow_all=False, parser=parser, crawl_delay=crawl_delay)

    def _space_out_first_request(
        self,
        origin_host: str,
        policy: RobotsPolicy,
        last_start_on_origin: float | None,
    ) -> None:
        """Hold the first real request back by the gap robots.txt asked for.

        The robots request reserved only the default interval, because the
        crawl delay was not known yet. Now that it is, push the host's next slot
        out from *the most recent request we actually made to that host* — which
        may have been a retry, not the first attempt.
        """
        if last_start_on_origin is None:
            return
        interval = self._interval_for(policy)
        self._limiter.bump(origin_host, last_start_on_origin + interval)
