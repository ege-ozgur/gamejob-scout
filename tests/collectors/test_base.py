"""The collector contract and the result it hands back.

Per-source isolation is *made possible* here, by typed errors and a contract
that says collectors raise rather than swallow. Whether isolation actually
happens is a property of the ingestion runner, and is tested there in milestone
1.9 rather than against a loop written inside a test.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from gamejob_scout.collectors import CollectionResult, Collector, CollectorError
from gamejob_scout.domain import ATSKind, JobListing
from tests.factories import make_job_listing

DISCOVERED_AT = datetime(2026, 9, 11, 8, 1, tzinfo=UTC)


class FakeCollector:
    """A stand-in source. Real adapters arrive in milestones 1.4 and 1.5."""

    def __init__(self, *, listings: tuple[JobListing, ...] = ()) -> None:
        self._listings = listings

    @property
    def source_key(self) -> str:
        return "example-studio-greenhouse"

    @property
    def company_key(self) -> str:
        return "example-studio"

    @property
    def source(self) -> ATSKind:
        return ATSKind.GREENHOUSE

    def collect(self, *, discovered_at: datetime) -> CollectionResult:
        return CollectionResult(found=len(self._listings), listings=self._listings)


class NotACollector:
    """Missing `collect`, so it does not satisfy the protocol."""

    @property
    def source_key(self) -> str:
        return "example-studio-greenhouse"


# mypy checks this assignment, which is the part `isinstance` cannot do:
# it verifies the method signatures, not merely that the names exist.
_conforms: Collector = FakeCollector()


def test_a_collector_satisfies_the_protocol_at_runtime() -> None:
    assert isinstance(FakeCollector(), Collector)


def test_an_incomplete_class_does_not() -> None:
    assert not isinstance(NotACollector(), Collector)


def test_a_collector_returns_what_it_found() -> None:
    listing = make_job_listing()

    result = FakeCollector(listings=(listing,)).collect(discovered_at=DISCOVERED_AT)

    assert result.found == 1
    assert result.listings == (listing,)


def test_collector_error_names_its_source() -> None:
    error = CollectorError("example-studio-greenhouse", "the board returned no JSON")

    assert error.source_key == "example-studio-greenhouse"
    assert "example-studio-greenhouse" in str(error)


# -- CollectionResult ------------------------------------------------------


def test_an_empty_result_is_valid() -> None:
    assert CollectionResult(found=0, listings=()).warnings == ()


def test_mapping_every_posting_is_valid() -> None:
    listing = make_job_listing()

    assert CollectionResult(found=1, listings=(listing,)).found == 1


def test_some_postings_may_fail_to_map() -> None:
    """The gap between found and listings is what makes a run partial."""
    result = CollectionResult(
        found=3,
        listings=(make_job_listing(),),
        warnings=("posting 2 had no title", "posting 3 had no apply link"),
    )

    assert len(result.listings) < result.found


def test_more_listings_than_postings_is_impossible() -> None:
    with pytest.raises(ValueError, match="cannot exceed found"):
        CollectionResult(found=0, listings=(make_job_listing(),))


def test_found_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        CollectionResult(found=-1, listings=())


@pytest.mark.parametrize("found", [True, False, 1.0, "2", None])
def test_found_must_really_be_an_integer(found: Any) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        CollectionResult(found=found, listings=())


@pytest.mark.parametrize("listings", [[], None, "abc"])
def test_listings_must_be_a_tuple(listings: Any) -> None:
    with pytest.raises(ValueError, match="listings must be a tuple"):
        CollectionResult(found=0, listings=listings)


def test_listings_must_hold_job_listings() -> None:
    with pytest.raises(ValueError, match="only JobListing"):
        CollectionResult(found=1, listings=("not a listing",))  # type: ignore[arg-type]


@pytest.mark.parametrize("warnings", [[], None, "oops"])
def test_warnings_must_be_a_tuple(warnings: Any) -> None:
    with pytest.raises(ValueError, match="warnings must be a tuple"):
        CollectionResult(found=0, listings=(), warnings=warnings)


def test_warnings_must_hold_strings() -> None:
    with pytest.raises(ValueError, match="only strings"):
        CollectionResult(found=0, listings=(), warnings=(1,))  # type: ignore[arg-type]


@pytest.mark.parametrize("warning", ["", "   ", "\n\t"])
def test_a_blank_warning_says_nothing(warning: str) -> None:
    with pytest.raises(ValueError, match="blank"):
        CollectionResult(found=0, listings=(), warnings=(warning,))


def test_repeated_warnings_are_kept() -> None:
    """Two identical warnings mean it happened twice, which is information."""
    repeated = ("could not parse a posting", "could not parse a posting")

    result = CollectionResult(found=2, listings=(), warnings=repeated)

    assert result.warnings == repeated


def test_warnings_are_stored_exactly_as_written() -> None:
    padded = "  posting 4 had no description  "

    result = CollectionResult(found=1, listings=(), warnings=(padded,))

    assert result.warnings == (padded,)
