"""A single job posting, with verified identity and change detection.

Two ideas carry most of the weight here.

**Stable identity.** A listing's ``id`` is derived from the source it came from
and that source's own job ID, so re-running ingestion finds the same job again
instead of inserting a duplicate.

**Content hashing.** ``content_hash`` covers only fields the company itself
publishes. It deliberately excludes everything we derive ourselves, so improving
our normalizer later cannot make every job look edited.
"""

import hashlib
import json
from datetime import datetime
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from gamejob_scout.domain.enums import ATSKind, ExperienceLevel, WorkplaceType
from gamejob_scout.domain.types import NonEmptyStr, Sha256Hex, Slug, UtcDatetime, VerbatimStr

HASHED_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "location_raw",
    "description_raw",
    "published_at",
    "application_url",
    "workplace_type_raw",
)
"""Fields that take part in change detection: source truth, and nothing else.

Excluded on purpose:

* ``id``, ``content_hash``, ``source``, ``source_key``, ``external_id``,
  ``company_key`` — identity, constant for the lifetime of a listing.
* ``source_url``, ``discovered_at`` — provenance. Hashing ``discovered_at``
  would mark every job as changed on every run.
* ``company_name`` — may come from our own monitored-company configuration
  rather than from the job source.
* ``description_text``, ``location``, ``workplace_type``, ``experience_level``
  and the ``years_required_*`` pair — everything the normalizer derives.
  Improving the normalizer would otherwise flag every stored job as edited.

``workplace_type_raw`` *is* hashed, because it is not ours: Lever publishes it,
and a company moving a role from on-site to remote is a real edit.

A changed hash therefore means exactly one thing: the company edited the posting.
"""


class JobContent(BaseModel):
    """A validated job posting without its identity fields.

    This exists so :meth:`JobListing.create` has something fully validated to
    compute the ID and hash *from*. Canonicalization (URL normalization, UTC
    conversion, whitespace stripping on our own labels) has already happened by
    the time an instance of this class exists, which is what makes the resulting
    hash reproducible. ``description_raw`` is the exception: it is stored
    character for character as the source sent it.

    Application code should use :class:`JobListing`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity and provenance.
    source: ATSKind
    source_key: Slug
    source_url: HttpUrl
    external_id: NonEmptyStr
    company_key: Slug
    company_name: NonEmptyStr
    discovered_at: UtcDatetime

    # Source truth: published by the company, stored as given.
    title: NonEmptyStr
    description_raw: VerbatimStr
    application_url: HttpUrl
    location_raw: str | None = None
    published_at: UtcDatetime | None = None
    workplace_type_raw: str | None = None
    """What the source itself said about where the work happens.

    Lever publishes this; Greenhouse does not, so it stays ``None`` there. Kept
    verbatim and uninterpreted — turning it into a :class:`WorkplaceType` is the
    normalizer's job.
    """

    # Derived by the normalizer in milestone 1.6. Every one of these is absent
    # from HASHED_FIELDS, so improving the rules never looks like a job edit.
    description_text: str | None = None
    location: str | None = None
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN
    experience_level: ExperienceLevel = ExperienceLevel.UNKNOWN
    years_required_min: float | None = Field(default=None, ge=0, le=60)
    years_required_max: float | None = Field(default=None, ge=0, le=60)

    @model_validator(mode="after")
    def _check_year_bounds(self) -> Self:
        low, high = self.years_required_min, self.years_required_max
        if low is not None and high is not None and low > high:
            raise ValueError(
                f"years_required_min ({low}) cannot exceed years_required_max ({high})",
            )
        return self


def make_job_id(source_key: str, external_id: str) -> str:
    """Build the stable ID for a listing.

    Keyed on ``source_key`` rather than the company, because one company may
    eventually run several boards and their job IDs could collide.
    """
    return f"{source_key}:{external_id}"


def compute_content_hash(content: JobContent) -> str:
    """Hash the fields in :data:`HASHED_FIELDS` into a hex SHA-256 digest.

    The payload is dumped in JSON mode so URLs, datetimes and enums become the
    same strings they would be in the database, then serialized with sorted keys
    and no incidental whitespace so the result depends only on the values.
    """
    payload = content.model_dump(mode="json", include=set(HASHED_FIELDS))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JobListing(JobContent):
    """A job posting with a verified ID and content hash.

    ``id`` and ``content_hash`` are ordinary fields, so a listing survives a
    round trip through JSON or a database row unchanged. They are re-derived and
    checked on every validation, so a wrong value cannot enter the system from
    any direction — a caller, a hand-edited file, or a stale database row.

    Build new listings with :meth:`create`, which computes both values.
    """

    id: NonEmptyStr
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def _verify_identity(self) -> Self:
        expected_id = make_job_id(self.source_key, self.external_id)
        if self.id != expected_id:
            raise ValueError(f"id must be {expected_id!r}, got {self.id!r}")

        expected_hash = compute_content_hash(self)
        if self.content_hash != expected_hash:
            raise ValueError(
                f"content_hash does not match this listing's content: "
                f"expected {expected_hash!r}, got {self.content_hash!r}",
            )

        return self

    @classmethod
    def create(
        cls,
        *,
        source: ATSKind,
        source_key: str,
        source_url: str | HttpUrl,
        external_id: str,
        company_key: str,
        company_name: str,
        discovered_at: datetime,
        title: str,
        description_raw: str,
        application_url: str | HttpUrl,
        location_raw: str | None = None,
        published_at: datetime | None = None,
        workplace_type_raw: str | None = None,
    ) -> "JobListing":
        """Create a listing, computing its ID and content hash.

        Validation happens twice on purpose. The first pass canonicalizes the
        input so the hash is computed from settled values; the second pass runs
        the finished listing back through the exact JSON path the database will
        use, so every construction proves the round trip works.

        Only source truth is accepted. Derived fields are deliberately absent
        from this signature, so a collector cannot invent an interpretation;
        those arrive later through
        :func:`~gamejob_scout.normalization.normalize_listing`.
        """
        content = JobContent(
            source=source,
            source_key=source_key,
            source_url=source_url,
            external_id=external_id,
            company_key=company_key,
            company_name=company_name,
            discovered_at=discovered_at,
            title=title,
            description_raw=description_raw,
            application_url=application_url,
            location_raw=location_raw,
            published_at=published_at,
            workplace_type_raw=workplace_type_raw,
        )
        return cls.model_validate(
            {
                **content.model_dump(mode="json"),
                "id": make_job_id(content.source_key, content.external_id),
                "content_hash": compute_content_hash(content),
            },
        )
