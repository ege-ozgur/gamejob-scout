"""Validated domain models.

This layer knows nothing about HTTP, databases, or language models. Everything
here is a plain Pydantic model that can be constructed, serialized to JSON, and
read back unchanged.
"""

from gamejob_scout.domain.candidate import CandidateProfile, Education, Project
from gamejob_scout.domain.company import COLLECTOR_BACKED_ATS, Company
from gamejob_scout.domain.enums import (
    ATSKind,
    ExperienceLevel,
    RunStatus,
    SourceStatus,
    WorkplaceType,
)
from gamejob_scout.domain.jobs import (
    HASHED_FIELDS,
    JobContent,
    JobListing,
    compute_content_hash,
    make_job_id,
)
from gamejob_scout.domain.runs import RunReport, SourceResult
from gamejob_scout.domain.types import (
    NonEmptyStr,
    Sha256Hex,
    Slug,
    StringTuple,
    UtcDatetime,
    VerbatimStr,
    dedupe_preserving_order,
    require_content,
    to_utc,
)

__all__ = [
    "COLLECTOR_BACKED_ATS",
    "HASHED_FIELDS",
    "ATSKind",
    "CandidateProfile",
    "Company",
    "Education",
    "ExperienceLevel",
    "JobContent",
    "JobListing",
    "NonEmptyStr",
    "Project",
    "RunReport",
    "RunStatus",
    "Sha256Hex",
    "Slug",
    "SourceResult",
    "SourceStatus",
    "StringTuple",
    "UtcDatetime",
    "VerbatimStr",
    "WorkplaceType",
    "compute_content_hash",
    "dedupe_preserving_order",
    "make_job_id",
    "require_content",
    "to_utc",
]
