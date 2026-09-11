"""Parsing and remembering robots.txt decisions.

This module holds the *policy*: what a robots document means and how results are
remembered. Actually fetching the document is the fetcher's job, because every
HTTP concern (timeouts, retries, rate limiting) already lives there.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from gamejob_scout.http.errors import RobotsError

__all__ = [
    "RobotsCache",
    "RobotsPolicy",
    "normalize_origin",
    "parse_robots_document",
    "robots_url_for",
]

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_origin(url: str) -> str:
    """The robots key for a URL: scheme, host and non-default port.

    Deliberately finer-grained than the rate-limit key. robots.txt is defined
    per origin, so http and https on one host are two documents even though they
    share one request budget.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port

    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def robots_url_for(origin: str) -> str:
    return f"{origin}/robots.txt"


def parse_robots_document(text: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    """What one origin's robots.txt permits.

    ``allow_all`` covers the case where the site answered with a client error,
    which by convention means "there are no rules here".
    """

    allow_all: bool
    parser: RobotFileParser | None = None
    crawl_delay: float | None = None

    @classmethod
    def allowing_everything(cls) -> "RobotsPolicy":
        return cls(allow_all=True)

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.allow_all or self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)


class RobotsCache:
    """Remembers each origin's outcome for the life of a fetcher.

    Failures are remembered too. A site with a broken robots.txt then costs one
    failed request per run instead of one per URL we wanted from it.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RobotsPolicy | RobotsError] = {}

    def get(self, origin: str) -> RobotsPolicy | RobotsError | None:
        return self._entries.get(origin)

    def store(self, origin: str, entry: RobotsPolicy | RobotsError) -> None:
        self._entries[origin] = entry

    def __len__(self) -> int:
        return len(self._entries)
