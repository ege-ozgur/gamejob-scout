"""What every careers source must look like from the outside.

A collector knows two things a shared fetcher cannot: which URLs its ATS uses,
and how to turn that ATS's payload into a :class:`JobListing`. Everything else —
timeouts, retries, robots.txt, rate limiting — belongs to
:class:`~gamejob_scout.http.fetcher.HttpFetcher`.

Collectors do **not** catch their own failures. A collector that swallows an
error is indistinguishable from one that legitimately found nothing, so errors
propagate and the ingestion runner decides what a failed source means. That
runner is milestone 1.9; this milestone only makes the isolation possible.

A concrete collector receives the shared fetcher through its constructor::

    class SomeAtsCollector:
        def __init__(self, fetcher: HttpFetcher, company: Company) -> None:
            self._fetcher = fetcher
            self._company = company

A Protocol cannot require that — it constrains only the members it declares —
so this is a convention held by review. The point of it is that one fetcher,
created once per run, is shared by every collector, which is what makes the
rate limiter, the robots cache and the connection pool work across sources.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from gamejob_scout.domain import ATSKind, JobListing, Slug, UtcDatetime
from gamejob_scout.domain.types import require_content
from gamejob_scout.errors import GameJobScoutError

__all__ = ["CollectionResult", "Collector", "CollectorError"]


class CollectorError(GameJobScoutError):
    """A collector could not produce results at all.

    For problems with individual postings, use
    :attr:`CollectionResult.warnings` instead — losing one posting is not a
    reason to discard the rest.
    """

    def __init__(self, source_key: str, message: str) -> None:
        super().__init__(f"{source_key}: {message}")
        self.source_key = source_key


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """What one collector produced in one run.

    ``found`` counts the postings the source returned, which can be larger than
    ``listings`` when some could not be understood. The difference is what makes
    a run *partial* rather than successful, so the two numbers are kept apart.
    """

    found: int
    listings: tuple[JobListing, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.found, bool) or not isinstance(self.found, int):
            raise ValueError("found must be an integer")
        if self.found < 0:
            raise ValueError("found must not be negative")

        if not isinstance(self.listings, tuple):
            raise ValueError("listings must be a tuple")
        for listing in self.listings:
            if not isinstance(listing, JobListing):
                raise ValueError("listings must contain only JobListing objects")

        if not isinstance(self.warnings, tuple):
            raise ValueError("warnings must be a tuple")
        for warning in self.warnings:
            if not isinstance(warning, str):
                raise ValueError("warnings must contain only strings")
            # Checked for content but stored exactly as written: repeated
            # warnings are meaningful, because each one happened.
            require_content(warning)

        if len(self.listings) > self.found:
            raise ValueError(
                f"listings ({len(self.listings)}) cannot exceed found ({self.found})",
            )


@runtime_checkable
class Collector(Protocol):
    """One careers source we can read.

    The ``Slug`` and ``UtcDatetime`` annotations describe the shape expected of
    each value. They are Pydantic constraints, so nothing enforces them at this
    boundary; enforcement happens where the values arrive in a real model —
    ``source_key`` and ``company_key`` when the runner builds a ``SourceResult``,
    and ``discovered_at`` inside ``JobListing.create``.
    """

    @property
    def source_key(self) -> Slug:
        """Stable identifier for this board, unique within a run."""

    @property
    def company_key(self) -> Slug:
        """The company that owns this board."""

    @property
    def source(self) -> ATSKind:
        """Which applicant tracking system this board runs on."""

    def collect(self, *, discovered_at: UtcDatetime) -> CollectionResult:
        """Read the source and map its postings.

        ``discovered_at`` is supplied by the caller so that every job found in
        one run shares a single timestamp.
        """
