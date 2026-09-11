"""Enumerations shared across the domain models.

All enums derive from ``StrEnum`` so that they serialize to plain strings
(``"greenhouse"`` rather than ``"ATSKind.GREENHOUSE"``) and compare equal to the
strings stored in JSON files and database columns.
"""

from enum import StrEnum


class ATSKind(StrEnum):
    """Which applicant tracking system a careers source is built on.

    A value is only added here once a collector exists that can actually read
    that system. ``CUSTOM`` means a bespoke careers page we cannot parse yet,
    ``UNKNOWN`` means nobody has verified it.
    """

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    """How far along a monitored company is, independent of which ATS it uses."""

    SUPPORTED = "supported"
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"


class WorkplaceType(StrEnum):
    """Where the work physically happens."""

    ON_SITE = "on_site"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class ExperienceLevel(StrEnum):
    """Seniority band.

    ``junior``, ``graduate`` and ``associate`` all map to :attr:`ENTRY` during
    normalization: job adverts use those words interchangeably, and keeping them
    apart would produce noisy, inconsistent matching.
    """

    INTERNSHIP = "internship"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    """Outcome of collecting one source, or of a whole ingestion run.

    ``SKIPPED`` at source level means the source was never attempted (for
    example because it is unsupported). At run level it means nothing was
    attempted at all.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
