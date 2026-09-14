"""Reading a company's Greenhouse job board.

Greenhouse publishes every board through one unauthenticated endpoint::

    GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

There is no pagination: the whole board arrives in a single response, with a
``meta.total`` alongside it. So one call to :meth:`GreenhouseCollector.collect`
makes exactly **one** request, and never follows up on individual postings.

Two quirks of the real API shape the mapping, both verified against a live board
rather than taken from the documentation:

* ``content`` arrives **HTML-entity-encoded** (``&lt;p&gt;`` rather than
  ``<p>``). That is Greenhouse's transport encoding, much like JSON's own string
  escaping, so it is decoded exactly once here. Decoding twice would corrupt
  entities that belong to the company's own text.
* ``first_published`` **is** present on the list endpoint, although the
  documentation describes it as single-job only. That is what lets us record a
  publication date without asking about each posting individually.

Nothing here interprets a posting. Deciding that "Remote - EMEA" means
``WorkplaceType.REMOTE`` belongs to the normalizer in milestone 1.6; this module
only moves the company's own words into the domain model unchanged.
"""

import html
import json
from datetime import datetime
from typing import Any, Final
from urllib.parse import quote

from pydantic import TypeAdapter, ValidationError

from gamejob_scout.collectors.base import CollectionResult, CollectorError
from gamejob_scout.domain import ATSKind, Company, JobListing, Slug
from gamejob_scout.http import HttpFetcher

__all__ = [
    "GREENHOUSE_API_BASE",
    "GreenhouseCollector",
    "board_jobs_url",
    "make_source_key",
]

GREENHOUSE_API_BASE: Final = "https://boards-api.greenhouse.io/v1/boards"

_SLUG = TypeAdapter(Slug)
"""Validates against the domain's own Slug rule rather than repeating its regex."""


def board_jobs_url(board_token: str) -> str:
    """The single endpoint a board is read from.

    ``content=true`` is what makes descriptions available, and is the reason one
    request is enough for a whole board.
    """
    safe_token = quote(board_token, safe="")
    return f"{GREENHOUSE_API_BASE}/{safe_token}/jobs?content=true"


def make_source_key(company: Company) -> str:
    """Derive a board's stable key.

    The board token is part of the key, not just the company and the ATS, so a
    company that later runs a second Greenhouse board gets a second distinct
    source rather than silently colliding with the first.
    """
    return f"{company.key}-greenhouse-{company.ats_identifier}"


def _checked_slug(value: str, description: str) -> str:
    """Validate a configured identifier against the domain's Slug rule.

    Configuration is ours, so this fails loudly at wiring time and shows the
    value. That is the opposite of how payload problems are handled below, where
    the offending value is never repeated.
    """
    try:
        return _SLUG.validate_python(value)
    except ValidationError as exc:
        raise ValueError(f"{description} is not a valid slug: {value!r}") from exc


class _SkipPosting(Exception):
    """One posting cannot be mapped.

    Carries a message that has already been made safe to report, so callers can
    append it to warnings without inspecting anything further.
    """

    def __init__(self, warning: str) -> None:
        super().__init__(warning)
        self.warning = warning


def _validated_external_id(value: object, index: int) -> str:
    """Accept only a positive JSON integer, then stringify it.

    This becomes half of ``JobListing.id``, which is a persisted primary key, so
    a blind ``str()`` would cheerfully store ``"None"``, ``"True"`` or
    ``"[1, 2]"`` as a job's identity forever.

    ``bool`` is excluded explicitly because it subclasses ``int``: without that
    check ``True`` would pass and become the identity ``"1"``.

    The rejected value is never quoted back. It is arbitrary payload, so the
    caller is told the index and nothing more.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _SkipPosting(f"job at index {index}: unusable 'id'")
    return str(value)


def _required_text(value: object, field: str, label: str) -> str:
    """Return a non-blank string exactly as it arrived, or skip the posting."""
    if not isinstance(value, str) or not value.strip():
        raise _SkipPosting(f"{label}: missing or blank {field!r}")
    return value


def _location_name(value: object) -> str | None:
    """Pull out the location's name, leaving its wording completely alone.

    Real boards are inconsistent here. One board carries both
    ``"Sariyer, Istanbul"`` and its dotted-capital variant, and reconciling
    those is the normalizer's job in milestone 1.6, not ours.
    """
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    return name if isinstance(name, str) else None


def _published_at(value: object) -> datetime | None:
    """Read ``first_published``, or give up quietly.

    A publication date is useful but optional, so anything unusable yields
    ``None`` rather than costing us the whole posting. A naive timestamp counts
    as unusable: the domain requires an aware datetime, and inventing a timezone
    would be worse than admitting we do not know.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _sanitized_reason(exc: ValidationError) -> str:
    """Describe a validation failure using only field names and error types.

    Pydantic's own string form embeds ``input_value=...``, which for a real
    posting would copy the whole job description into a warning, and from there
    into run reports, logs and the database. Only ``loc`` and ``type`` are read
    here: ``input``, ``ctx`` and ``msg`` are all capable of carrying the value.
    """
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "<model>"
        parts.append(f"{location} ({error['type']})")
    return "invalid " + ", ".join(parts)


class GreenhouseCollector:
    """Reads one Greenhouse board and maps it into domain listings.

    The shared :class:`~gamejob_scout.http.fetcher.HttpFetcher` arrives through
    the constructor so that every collector in a run shares one rate limiter,
    robots cache and connection pool.

    Failures are not swallowed. A fetch problem propagates as the typed
    ``FetchError`` it already is, and a board that cannot be read at all raises
    :class:`~gamejob_scout.collectors.base.CollectorError`. Only individual
    unusable postings are downgraded to warnings, because losing one posting is
    no reason to discard the rest.
    """

    def __init__(
        self,
        fetcher: HttpFetcher,
        company: Company,
        *,
        source_key: str | None = None,
    ) -> None:
        if company.ats is not ATSKind.GREENHOUSE:
            raise ValueError(
                f"{company.key!r} is configured as {company.ats.value!r}, not 'greenhouse'",
            )
        if company.ats_identifier is None:
            raise ValueError(f"{company.key!r} has no ats_identifier to use as a board token")

        self._board_token = _checked_slug(
            company.ats_identifier,
            f"board token for {company.key!r}",
        )
        self._source_key = _checked_slug(
            make_source_key(company) if source_key is None else source_key,
            f"source key for {company.key!r}",
        )
        self._fetcher = fetcher
        self._company = company

    @property
    def source_key(self) -> Slug:
        return self._source_key

    @property
    def company_key(self) -> Slug:
        return self._company.key

    @property
    def source(self) -> ATSKind:
        return ATSKind.GREENHOUSE

    def collect(self, *, discovered_at: datetime) -> CollectionResult:
        """Fetch the board once and map every posting it returned."""
        url = board_jobs_url(self._board_token)
        document = self._fetcher.get(url)

        payload = self._decoded_body(document.text)
        entries = self._job_entries(payload)

        warnings = self._meta_warnings(payload, len(entries))
        listings: list[JobListing] = []

        for index, entry in enumerate(entries):
            try:
                listings.append(
                    self._to_listing(
                        entry,
                        index=index,
                        discovered_at=discovered_at,
                        source_url=url,
                        warnings=warnings,
                    ),
                )
            except _SkipPosting as skipped:
                warnings.append(skipped.warning)

        # `found` counts what the board returned, not what we understood, so the
        # gap between the two is what makes a run partial rather than successful.
        return CollectionResult(
            found=len(entries),
            listings=tuple(listings),
            warnings=tuple(warnings),
        )

    def _decoded_body(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CollectorError(self._source_key, "board response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise CollectorError(self._source_key, "board response was not a JSON object")
        return payload

    def _job_entries(self, payload: dict[str, Any]) -> list[Any]:
        if "jobs" not in payload:
            raise CollectorError(self._source_key, "board response has no 'jobs' array")
        entries = payload["jobs"]
        if not isinstance(entries, list):
            raise CollectorError(self._source_key, "board response 'jobs' was not an array")
        return entries

    def _meta_warnings(self, payload: dict[str, Any], job_count: int) -> list[str]:
        """Check the board's own count against what it actually sent.

        ``meta`` is optional metadata, so its absence is not worth mentioning. A
        count that disagrees with the payload is, because that is what would
        show up first if Greenhouse ever introduced pagination.
        """
        if "meta" not in payload:
            return []

        meta = payload["meta"]
        if not isinstance(meta, dict):
            return ["board response 'meta' was not an object"]
        if "total" not in meta:
            return []

        total = meta["total"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            return ["board response 'meta.total' was not a non-negative integer"]
        if total != job_count:
            return [f"board reported {total} jobs but returned {job_count}"]
        return []

    def _to_listing(
        self,
        entry: object,
        *,
        index: int,
        discovered_at: datetime,
        source_url: str,
        warnings: list[str],
    ) -> JobListing:
        if not isinstance(entry, dict):
            raise _SkipPosting(f"job at index {index}: entry was not an object")

        # Validated before anything else, because every label below quotes it and
        # only an id that has passed this check is safe to repeat.
        external_id = _validated_external_id(entry.get("id"), index)
        label = f"job at index {index} (id {external_id})"

        title = _required_text(entry.get("title"), "title", label)
        content = _required_text(entry.get("content"), "content", label)
        application_url = _required_text(entry.get("absolute_url"), "absolute_url", label)

        raw_published = entry.get("first_published")
        published_at = _published_at(raw_published)
        if raw_published is not None and published_at is None:
            warnings.append(f"{label}: unusable 'first_published', continuing without it")

        try:
            return JobListing.create(
                source=ATSKind.GREENHOUSE,
                source_key=self._source_key,
                source_url=source_url,
                external_id=external_id,
                company_key=self._company.key,
                company_name=self._company.name,
                discovered_at=discovered_at,
                title=title,
                # Decoded exactly once: see this module's docstring.
                description_raw=html.unescape(content),
                application_url=application_url,
                location_raw=_location_name(entry.get("location")),
                published_at=published_at,
            )
        except ValidationError as exc:
            raise _SkipPosting(f"{label}: {_sanitized_reason(exc)}") from exc
