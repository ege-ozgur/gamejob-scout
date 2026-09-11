"""A company we monitor for job openings."""

from typing import Self

from pydantic import BaseModel, ConfigDict, HttpUrl, model_validator

from gamejob_scout.domain.enums import ATSKind, SourceStatus
from gamejob_scout.domain.types import NonEmptyStr, Slug, UtcDatetime

COLLECTOR_BACKED_ATS = frozenset({ATSKind.GREENHOUSE, ATSKind.LEVER})
"""ATS kinds a collector can actually read. Extend this only when one exists."""


class Company(BaseModel):
    """A studio or technology company, and the state of our support for it.

    The invariants below encode the project's "verify before adding" rule in the
    type system: a company cannot be marked ``SUPPORTED`` without the concrete
    evidence that somebody checked it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: Slug
    name: NonEmptyStr
    website: HttpUrl | None = None
    careers_url: HttpUrl | None = None
    ats: ATSKind = ATSKind.UNKNOWN
    ats_identifier: NonEmptyStr | None = None
    status: SourceStatus = SourceStatus.PLANNED
    country: NonEmptyStr | None = None
    notes: str | None = None
    verified_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_support_evidence(self) -> Self:
        if self.ats in COLLECTOR_BACKED_ATS and self.ats_identifier is None:
            raise ValueError(f"ats_identifier is required when ats is {self.ats.value!r}")

        if self.status is not SourceStatus.SUPPORTED:
            return self

        if self.ats not in COLLECTOR_BACKED_ATS:
            raise ValueError(
                f"status 'supported' requires a collector-backed ats, got {self.ats.value!r}",
            )
        if self.careers_url is None:
            raise ValueError("status 'supported' requires careers_url")
        if self.verified_at is None:
            raise ValueError("status 'supported' requires verified_at")

        return self
