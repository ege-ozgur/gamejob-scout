"""Reading a company's Lever job board.

Lever publishes every board through one unauthenticated endpoint::

    GET https://api.lever.co/v0/postings/{site}?mode=json

Four things about the real API shape the whole design, all verified against a live
board rather than taken from the documentation:

* The response is a **bare JSON array**, not an object. There is no ``meta``, so
  there is no count to check the payload against.
* It **paginates** with ``skip`` and ``limit``, and ``limit`` is documented only
  as "at most N". A short page therefore proves nothing, so pagination advances
  by the number of entries actually returned and stops only on an empty page.
* ``description`` is **real HTML**, not entity-encoded. The opposite of
  Greenhouse, so nothing is unescaped here.
* There is **no publication timestamp**. ``createdAt`` exists but is the
  posting's creation time, so it is deliberately not used.

The one place this collector genuinely *builds* something rather than copying it
is ``description_raw``. Lever splits a posting across ``description``, ``lists``
and ``additional``, and the requirements usually live only in ``lists`` — on the
board this was verified against, every single posting did. Taking ``description``
alone would quietly discard the most useful part of every job, so the pieces are
composed with the fixed template in :func:`compose_description`. That is a
construction, not a transcription, which is worth knowing given that
``description_raw`` is documented as source truth elsewhere.

Nothing here interprets a posting. ``workplaceType``, ``categories.commitment``
and the rest are left alone: turning them into domain values is the normalizer's
job in milestone 1.6.
"""

import html
import json
import re
from datetime import datetime
from typing import Any, Final

from pydantic import TypeAdapter, ValidationError

from gamejob_scout.collectors.base import CollectionResult, CollectorError, JobBoardFetcher
from gamejob_scout.domain import ATSKind, Company, JobListing, Slug

__all__ = [
    "LEVER_API_BASE",
    "LEVER_MAX_ID_LENGTH",
    "LEVER_MAX_PAGES",
    "LEVER_PAGE_SIZE",
    "LeverCollector",
    "board_url",
    "compose_description",
    "make_source_key",
    "postings_url",
]

LEVER_API_BASE: Final = "https://api.lever.co/v0/postings"

LEVER_PAGE_SIZE: Final = 100
"""Postings requested per page, and the ceiling we accept for ``limit``."""

LEVER_MAX_PAGES: Final = 20
"""Hard bound on one ``collect()`` call, so a misbehaving board cannot run away."""

LEVER_MAX_ID_LENGTH: Final = 128
"""Longest posting ID we will store.

The longest identifier any ATS we support actually emits is a 36-character UUID,
so this leaves roughly three and a half times the headroom while keeping the
composed ``{source_key}:{external_id}`` primary key short enough to index and to
print in a warning. Without a bound, one malformed payload could plant a
multi-megabyte primary key.
"""

_SLUG = TypeAdapter(Slug)
"""Validates against the domain's own Slug rule rather than repeating its regex."""

_UNSAFE_IN_ID = re.compile(r"[\s:\x00-\x1f\x7f]")
"""Characters that would corrupt an identifier.

``:`` separates the two halves of ``JobListing.id``, so allowing it would make
the composed identity ambiguous. Whitespace and control characters wreck log
lines, URLs and database keys.
"""


def _checked_slug(value: str, description: str) -> str:
    """Validate a configured identifier against the domain's Slug rule.

    Configuration is ours, so this fails loudly and shows the value. That is the
    opposite of how payload problems are handled below, where the offending value
    is never repeated.
    """
    try:
        return _SLUG.validate_python(value)
    except ValidationError as exc:
        raise ValueError(f"{description} is not a valid slug: {value!r}") from exc


def _checked_count(name: str, value: int, *, minimum: int, maximum: int | None = None) -> int:
    """Validate a pagination argument.

    ``bool`` is rejected explicitly because it subclasses ``int``: without that
    check ``limit=True`` would silently mean one posting per page.
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, not a bool")
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def board_url(site: str) -> str:
    """The canonical URL for a board, without pagination.

    Recorded as a listing's ``source_url`` so provenance reads the same however
    many pages a particular run happened to need.

    Only the site is validated here: this helper takes a bare string and has no
    ``Company`` to inspect. The slug check is what keeps a bad token from being
    interpolated into somebody else's URL.
    """
    return f"{LEVER_API_BASE}/{_checked_slug(site, 'lever site')}?mode=json"


def postings_url(site: str, *, skip: int = 0, limit: int = LEVER_PAGE_SIZE) -> str:
    """The URL for one page of postings."""
    token = _checked_slug(site, "lever site")
    start = _checked_count("skip", skip, minimum=0)
    size = _checked_count("limit", limit, minimum=1, maximum=LEVER_PAGE_SIZE)
    return f"{LEVER_API_BASE}/{token}?mode=json&skip={start}&limit={size}"


def _lever_site(company: Company) -> str:
    """Confirm a company really is a Lever board, and hand back its site token.

    One place decides what a usable Lever company looks like, so the exported
    helper and the collector cannot drift apart on it.
    """
    if company.ats is not ATSKind.LEVER:
        raise ValueError(f"{company.key!r} is configured as {company.ats.value!r}, not 'lever'")
    if company.ats_identifier is None:
        raise ValueError(f"{company.key!r} has no ats_identifier to use as a Lever site")
    return _checked_slug(company.ats_identifier, f"lever site for {company.key!r}")


def make_source_key(company: Company) -> str:
    """Derive a board's stable key.

    The site token is part of the key, not just the company and the ATS, so a
    company that later runs a second Lever site gets a second distinct source
    rather than silently colliding with the first.
    """
    site = _lever_site(company)
    return _checked_slug(f"{company.key}-lever-{site}", f"source key for {company.key!r}")


class _SkipPosting(Exception):
    """One posting cannot be mapped.

    Carries a message that has already been made safe to report, so callers can
    append it to warnings without inspecting anything further.
    """

    def __init__(self, warning: str) -> None:
        super().__init__(warning)
        self.warning = warning


def _id_problem(value: str) -> str | None:
    """Why this ID is unusable, or ``None`` if it is fine.

    Takes an already-confirmed string. Never quotes the value: a failing ID is
    arbitrary payload, so only the *kind* of problem is reported.
    """
    if not value.strip():
        return "blank"
    if len(value) > LEVER_MAX_ID_LENGTH:
        return f"longer than {LEVER_MAX_ID_LENGTH} characters"
    if _UNSAFE_IN_ID.search(value):
        return "contains whitespace, a colon, or a control character"
    return None


def _validated_external_id(value: object, index: int) -> str:
    """Check an ID is safe to become half of a persisted primary key.

    Lever documents ``id`` only as a "unique posting ID". Live values look like
    UUIDs, but nothing promises that, so the shape is deliberately not
    constrained — only what would corrupt identity is. The value is stored
    exactly as it arrived: rewriting an identifier, even just its case, would let
    one posting enter the system under two identities.
    """
    if not isinstance(value, str):
        raise _SkipPosting(f"posting at index {index}: unusable 'id' (not a string)")
    problem = _id_problem(value)
    if problem is not None:
        raise _SkipPosting(f"posting at index {index}: unusable 'id' ({problem})")
    return value


def _safe_external_id(value: object) -> str | None:
    """The ID if it is usable, otherwise ``None``. Raises nothing.

    Used to look at a whole page's IDs before mapping it, for the repeated-page
    guard, where a problem is not yet worth reporting.
    """
    if not isinstance(value, str) or _id_problem(value) is not None:
        return None
    return value


def _required_text(value: object, field: str, label: str) -> str:
    """Return a non-blank string exactly as it arrived, or skip the posting."""
    if not isinstance(value, str) or not value.strip():
        raise _SkipPosting(f"{label}: missing or blank {field!r}")
    return value


def _location(categories: object) -> str | None:
    """Pull the location out of ``categories``, leaving its wording alone.

    Deciding that "Remote - Europe" means somewhere in particular belongs to the
    normalizer in milestone 1.6.
    """
    if not isinstance(categories, dict):
        return None
    location = categories.get("location")
    return location if isinstance(location, str) else None


def compose_description(posting: dict[str, Any]) -> str:
    """Assemble a posting's full text from the fields Lever splits it across.

    ``description`` + each list + ``additional``, in payload order. The result is
    a pure function of Lever's own values, so a listing's content hash stays
    stable unless the company actually edits the posting.

    Two details are ours rather than Lever's, and both are deliberate:

    * Each list is wrapped in ``<ul>``, because Lever ships bare ``<li>`` items
      that would otherwise be invalid HTML.
    * ``lists[].text`` is plain text and so is HTML-escaped. An unescaped ``&``
      or ``<`` in a list name would otherwise produce broken markup.
    """
    parts: list[str] = []

    description = posting.get("description")
    if isinstance(description, str):
        parts.append(description)

    entries = posting.get("lists")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            name = entry.get("text")
            heading = ""
            if isinstance(name, str) and name.strip():
                heading = f"<h3>{html.escape(name)}</h3>"
            parts.append(f"<section>{heading}<ul>{content}</ul></section>")

    additional = posting.get("additional")
    if isinstance(additional, str):
        parts.append(additional)

    return "".join(parts)


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


class LeverCollector:
    """Reads one Lever board and maps it into domain listings.

    The shared fetcher arrives through the constructor so that every collector in
    a run shares one rate limiter, robots cache and connection pool.

    Failures are not swallowed. A fetch problem propagates as the typed
    ``FetchError`` it already is, and a board that cannot be read at all raises
    :class:`~gamejob_scout.collectors.base.CollectorError`. Only individual
    unusable postings are downgraded to warnings, because losing one posting is
    no reason to discard the rest.
    """

    def __init__(
        self,
        fetcher: JobBoardFetcher,
        company: Company,
        *,
        source_key: str | None = None,
    ) -> None:
        # Both of these are the exported helpers, so construction and direct use
        # of the public API cannot disagree about what is acceptable.
        self._site = _lever_site(company)
        self._source_key = (
            make_source_key(company)
            if source_key is None
            else _checked_slug(source_key, f"source key for {company.key!r}")
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
        return ATSKind.LEVER

    def collect(self, *, discovered_at: datetime) -> CollectionResult:
        """Read every page of the board and map the postings it returned."""
        source_url = board_url(self._site)
        warnings: list[str] = []
        listings: list[JobListing] = []
        seen: set[str] = set()
        found = 0
        skip = 0
        pages = 0

        while pages < LEVER_MAX_PAGES:
            page = self._fetch_page(skip)
            pages += 1

            # An empty page is the only positive evidence that a board has
            # ended. `limit` is documented as "at most N", so a short page is
            # not a signal about anything.
            if not page:
                break

            page_ids = {found_id for entry in page if (found_id := self._entry_id(entry))}
            if page_ids and page_ids <= seen:
                warnings.append("board repeated a page of postings; stopping pagination")
                break

            for offset, entry in enumerate(page):
                try:
                    listings.append(
                        self._to_listing(
                            entry,
                            index=found + offset,
                            discovered_at=discovered_at,
                            source_url=source_url,
                            seen=seen,
                        ),
                    )
                except _SkipPosting as skipped:
                    warnings.append(skipped.warning)

            found += len(page)
            skip += len(page)
        else:
            warnings.append(
                f"stopped after {LEVER_MAX_PAGES} pages; collection may be incomplete",
            )

        return CollectionResult(
            found=found,
            listings=tuple(listings),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _entry_id(entry: object) -> str | None:
        if not isinstance(entry, dict):
            return None
        return _safe_external_id(entry.get("id"))

    def _fetch_page(self, skip: int) -> list[Any]:
        url = postings_url(self._site, skip=skip, limit=LEVER_PAGE_SIZE)
        document = self._fetcher.get(url)

        try:
            payload = json.loads(document.text)
        except json.JSONDecodeError as exc:
            raise CollectorError(self._source_key, "board response was not valid JSON") from exc
        if not isinstance(payload, list):
            raise CollectorError(self._source_key, "board response was not a JSON array")
        return payload

    def _to_listing(
        self,
        entry: object,
        *,
        index: int,
        discovered_at: datetime,
        source_url: str,
        seen: set[str],
    ) -> JobListing:
        if not isinstance(entry, dict):
            raise _SkipPosting(f"posting at index {index}: entry was not an object")

        # Validated before anything else, because every label below quotes it and
        # only an ID that has passed this check is safe to repeat.
        external_id = _validated_external_id(entry.get("id"), index)
        label = f"posting at index {index} (id {external_id})"

        if external_id in seen:
            raise _SkipPosting(f"{label}: duplicate id, keeping the first occurrence")

        title = _required_text(entry.get("text"), "text", label)
        application_url = _required_text(entry.get("hostedUrl"), "hostedUrl", label)
        description_raw = compose_description(entry)
        if not description_raw.strip():
            raise _SkipPosting(f"{label}: no description content in any field")

        try:
            listing = JobListing.create(
                source=ATSKind.LEVER,
                source_key=self._source_key,
                source_url=source_url,
                external_id=external_id,
                company_key=self._company.key,
                company_name=self._company.name,
                discovered_at=discovered_at,
                title=title,
                description_raw=description_raw,
                application_url=application_url,
                location_raw=_location(entry.get("categories")),
                # Lever publishes no publication timestamp. `createdAt` is the
                # posting's creation time, and substituting it would record a
                # date the company never published.
                published_at=None,
            )
        except ValidationError as exc:
            raise _SkipPosting(f"{label}: {_sanitized_reason(exc)}") from exc

        seen.add(external_id)
        return listing
