"""Builders for test data.

Everything here is invented. "Example Studio" is not a real company, and the
URLs point at ``example.com``, which exists for exactly this purpose. No real
company, careers URL, ATS identifier, or job posting appears in the test suite.

Each builder takes keyword overrides so a test can change the one field it cares
about and leave the rest alone.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gamejob_scout.domain import (
    ATSKind,
    CandidateProfile,
    Company,
    ExperienceLevel,
    JobListing,
    RunReport,
    RunStatus,
    SourceResult,
    SourceStatus,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PROFILE_PATH = _REPO_ROOT / "examples" / "candidate_profile.example.json"

RUN_STARTED_AT = datetime(2026, 9, 11, 8, 0, 0, tzinfo=UTC)
RUN_FINISHED_AT = datetime(2026, 9, 11, 8, 5, 0, tzinfo=UTC)
DISCOVERED_AT = datetime(2026, 9, 11, 8, 1, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 9, 1, 12, 30, 0, tzinfo=UTC)


def make_candidate_profile(**overrides: Any) -> CandidateProfile:
    defaults: dict[str, Any] = {
        "headline": "Recent graduate looking for a first gameplay or software role",
        "target_roles": ["Gameplay Programmer", "Junior Software Engineer"],
        "experience_level": ExperienceLevel.ENTRY,
        "years_of_experience": 0.5,
        "preferred_locations": ["Istanbul, Turkey"],
        "authorized_to_work_in": ["Turkey"],
        "skills": ["Gameplay systems", "Debugging"],
        "programming_languages": ["C++", "Python"],
        "game_engines": ["Unreal Engine"],
    }
    return CandidateProfile(**{**defaults, **overrides})


def make_company(**overrides: Any) -> Company:
    defaults: dict[str, Any] = {
        "key": "example-studio",
        "name": "Example Studio",
        "website": "https://example.com/",
        "careers_url": "https://example.com/careers",
        "ats": ATSKind.GREENHOUSE,
        "ats_identifier": "examplestudio",
        "status": SourceStatus.SUPPORTED,
        "country": "Turkey",
        "verified_at": RUN_STARTED_AT,
    }
    return Company(**{**defaults, **overrides})


def make_job_listing(**overrides: Any) -> JobListing:
    defaults: dict[str, Any] = {
        "source": ATSKind.GREENHOUSE,
        "source_key": "example-studio-greenhouse",
        "source_url": "https://example.com/boards/examplestudio",
        "external_id": "12345",
        "company_key": "example-studio",
        "company_name": "Example Studio",
        "discovered_at": DISCOVERED_AT,
        "title": "Gameplay Programmer",
        "description_raw": "<p>Work on gameplay systems.</p>",
        "application_url": "https://example.com/jobs/12345/apply",
        "location_raw": "Istanbul, Turkey",
        "published_at": PUBLISHED_AT,
    }
    return JobListing.create(**{**defaults, **overrides})


def make_source_result(**overrides: Any) -> SourceResult:
    defaults: dict[str, Any] = {
        "source_key": "example-studio-greenhouse",
        "company_key": "example-studio",
        "source": ATSKind.GREENHOUSE,
        "status": RunStatus.SUCCESS,
        "started_at": RUN_STARTED_AT,
        "finished_at": RUN_FINISHED_AT,
        "jobs_found": 10,
        "jobs_new": 3,
        "jobs_updated": 2,
        "jobs_unchanged": 5,
    }
    return SourceResult(**{**defaults, **overrides})


def make_skipped_source(**overrides: Any) -> SourceResult:
    defaults: dict[str, Any] = {
        "source_key": "other-studio-custom",
        "company_key": "other-studio",
        "source": ATSKind.CUSTOM,
        "status": RunStatus.SKIPPED,
        "started_at": RUN_STARTED_AT,
        "finished_at": RUN_STARTED_AT,
        "message": "custom careers page is not supported yet",
    }
    return SourceResult(**{**defaults, **overrides})


def make_failed_source(**overrides: Any) -> SourceResult:
    defaults: dict[str, Any] = {
        "source_key": "broken-studio-lever",
        "company_key": "broken-studio",
        "source": ATSKind.LEVER,
        "status": RunStatus.FAILED,
        "started_at": RUN_STARTED_AT,
        "finished_at": RUN_FINISHED_AT,
        "message": "connection timed out after 20s",
    }
    return SourceResult(**{**defaults, **overrides})


def make_run_report(**overrides: Any) -> RunReport:
    defaults: dict[str, Any] = {
        "started_at": RUN_STARTED_AT,
        "finished_at": RUN_FINISHED_AT,
        "sources": (make_source_result(),),
    }
    return RunReport(**{**defaults, **overrides})
