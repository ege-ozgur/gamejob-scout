"""Rules for a monitored company.

The point of these tests is that a company cannot be marked ``supported``
without the evidence that someone actually checked it.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gamejob_scout.domain import ATSKind, Company, SourceStatus
from tests.factories import make_company


def test_a_fully_verified_company_is_valid() -> None:
    company = make_company()

    assert company.status is SourceStatus.SUPPORTED
    assert company.ats is ATSKind.GREENHOUSE
    assert company.ats_identifier == "examplestudio"


def test_a_planned_company_needs_almost_nothing() -> None:
    company = Company(key="unchecked-studio", name="Unchecked Studio")

    assert company.status is SourceStatus.PLANNED
    assert company.ats is ATSKind.UNKNOWN
    assert company.careers_url is None


@pytest.mark.parametrize("missing", ["ats_identifier", "careers_url", "verified_at"])
def test_supported_requires_its_evidence(missing: str) -> None:
    with pytest.raises(ValidationError, match=missing):
        make_company(**{missing: None})


def test_supported_requires_a_collector_backed_ats() -> None:
    with pytest.raises(ValidationError, match="collector-backed"):
        make_company(ats=ATSKind.CUSTOM, ats_identifier=None)


@pytest.mark.parametrize("ats", [ATSKind.GREENHOUSE, ATSKind.LEVER])
def test_known_ats_always_needs_an_identifier(ats: ATSKind) -> None:
    """True even for a planned company: we never guess a board token."""
    with pytest.raises(ValidationError, match="ats_identifier"):
        Company(
            key="unchecked-studio",
            name="Unchecked Studio",
            ats=ats,
            status=SourceStatus.PLANNED,
        )


def test_an_unsupported_custom_page_is_recorded_honestly() -> None:
    company = Company(
        key="custom-studio",
        name="Custom Studio",
        website="https://example.com/",
        ats=ATSKind.CUSTOM,
        status=SourceStatus.UNSUPPORTED,
        notes="bespoke careers page, no public feed found",
    )

    assert company.status is SourceStatus.UNSUPPORTED


@pytest.mark.parametrize("key", ["example-studio", "studio2", "a-b-c"])
def test_valid_company_keys(key: str) -> None:
    assert make_company(key=key).key == key


@pytest.mark.parametrize(
    "key",
    ["Example Studio", "example--studio", "-example", "example_studio", "Example-Studio", ""],
)
def test_invalid_company_keys_are_rejected_not_coerced(key: str) -> None:
    with pytest.raises(ValidationError, match="key"):
        make_company(key=key)


def test_verified_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="verified_at"):
        make_company(verified_at=datetime(2026, 9, 11, 8, 0))


def test_verified_at_is_converted_to_utc() -> None:
    company = make_company(verified_at="2026-09-11T13:00:00+03:00")

    assert company.verified_at == datetime(2026, 9, 11, 10, 0, tzinfo=UTC)


def test_website_must_be_a_real_url() -> None:
    with pytest.raises(ValidationError, match="website"):
        make_company(website="example.com")
