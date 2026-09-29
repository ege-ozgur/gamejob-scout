"""Normalizing a whole listing, over both collectors' real fixture output.

The invariants here are the ones that protect the 1.2 design: normalization adds
our reading of a posting without disturbing its identity or its change detection.
"""

from typing import Any

import pytest

from gamejob_scout.collectors import GreenhouseCollector, LeverCollector
from gamejob_scout.collectors.base import JobBoardFetcher
from gamejob_scout.domain import ATSKind, ExperienceLevel, JobListing, WorkplaceType
from gamejob_scout.http import FetchedDocument
from gamejob_scout.normalization import normalize_listing
from tests.collectors.test_greenhouse import load_fixture as load_greenhouse
from tests.collectors.test_lever import load_fixture as load_lever
from tests.factories import DISCOVERED_AT, make_company, make_job_listing


class Canned:
    """Serves fixture bodies; satisfies JobBoardFetcher structurally."""

    def __init__(self, *bodies: str) -> None:
        self.bodies = list(bodies)

    def get(self, url: str) -> FetchedDocument:
        body = self.bodies.pop(0) if self.bodies else "[]"
        return FetchedDocument(url=url, status_code=200, headers={}, text=body)


def greenhouse_listings() -> tuple[JobListing, ...]:
    fetcher: JobBoardFetcher = Canned(load_greenhouse("board_two_jobs"))
    return (
        GreenhouseCollector(fetcher, make_company())
        .collect(
            discovered_at=DISCOVERED_AT,
        )
        .listings
    )


def lever_listings() -> tuple[JobListing, ...]:
    fetcher: JobBoardFetcher = Canned(load_lever("board_two_postings"), "[]")
    company = make_company(ats=ATSKind.LEVER, ats_identifier="examplestudio")
    return LeverCollector(fetcher, company).collect(discovered_at=DISCOVERED_AT).listings


def all_listings() -> list[JobListing]:
    return [*greenhouse_listings(), *lever_listings()]


# -- the invariants that protect the 1.2 design ----------------------------


def test_identity_and_hash_survive_normalization() -> None:
    """Derived fields are outside HASHED_FIELDS, so neither may move."""
    for listing in all_listings():
        normalized = normalize_listing(listing)

        assert normalized.id == listing.id
        assert normalized.content_hash == listing.content_hash


def test_normalization_is_idempotent() -> None:
    """Every run reads the unchanged description_raw, never its own output."""
    for listing in all_listings():
        once = normalize_listing(listing)
        assert normalize_listing(once) == once


def test_the_input_listing_is_not_mutated() -> None:
    listing = greenhouse_listings()[0]
    before = listing.model_dump(mode="json")

    normalize_listing(listing)

    assert listing.model_dump(mode="json") == before


def test_a_normalized_listing_round_trips_through_json() -> None:
    for listing in all_listings():
        normalized = normalize_listing(listing)

        assert JobListing.model_validate(normalized.model_dump(mode="json")) == normalized


def test_source_truth_is_left_completely_alone() -> None:
    for listing in all_listings():
        normalized = normalize_listing(listing)

        assert normalized.description_raw == listing.description_raw
        assert normalized.location_raw == listing.location_raw
        assert normalized.title == listing.title
        assert normalized.published_at == listing.published_at
        assert normalized.workplace_type_raw == listing.workplace_type_raw


# -- what it actually derives ----------------------------------------------


def test_a_greenhouse_posting_is_read_correctly() -> None:
    listing = normalize_listing(greenhouse_listings()[0])

    assert listing.description_text is not None
    assert "roleYou" not in listing.description_text, "words must not run together"
    assert "tools & pipelines" in listing.description_text
    assert listing.location == "Kadıköy, İstanbul"
    assert listing.workplace_type is WorkplaceType.UNKNOWN, "a city is not a signal"
    assert listing.experience_level is ExperienceLevel.UNKNOWN


def test_a_remote_greenhouse_posting_is_read_correctly() -> None:
    listing = normalize_listing(greenhouse_listings()[1])

    assert listing.location == "Remote - Europe"
    assert listing.workplace_type is WorkplaceType.REMOTE
    assert listing.experience_level is ExperienceLevel.ENTRY, "'Junior Technical Artist'"


def test_a_lever_posting_keeps_its_requirements_in_the_text() -> None:
    """The bullets live only in `lists`, which is why they are composed in 1.5."""
    listing = normalize_listing(lever_listings()[0])

    assert listing.description_text is not None
    assert "Strong C++ and debugging skills" in listing.description_text
    assert "Build and maintain gameplay systems" in listing.description_text


def test_lever_states_its_workplace_type_and_we_believe_it() -> None:
    listings = [normalize_listing(job) for job in lever_listings()]

    assert listings[0].workplace_type_raw == "onsite"
    assert listings[0].workplace_type is WorkplaceType.ON_SITE
    assert listings[1].workplace_type_raw == "remote"
    assert listings[1].workplace_type is WorkplaceType.REMOTE


def test_greenhouse_has_no_raw_workplace_type_to_believe() -> None:
    for listing in greenhouse_listings():
        assert listing.workplace_type_raw is None


# -- nothing to go on ------------------------------------------------------


def test_a_listing_with_no_signals_normalizes_without_complaint() -> None:
    listing = make_job_listing(
        title="Gameplay Programmer",
        location_raw=None,
        description_raw="<p>Work on games.</p>",
    )

    normalized = normalize_listing(listing)

    assert normalized.location is None
    assert normalized.workplace_type is WorkplaceType.UNKNOWN
    assert normalized.experience_level is ExperienceLevel.UNKNOWN
    assert normalized.years_required_min is None
    assert normalized.years_required_max is None
    assert normalized.description_text == "Work on games."


def test_a_description_of_pure_markup_leaves_no_text() -> None:
    normalized = normalize_listing(make_job_listing(description_raw="<div><span> </span></div>"))

    assert normalized.description_text is None
    assert normalized.years_required_min is None


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("<p>We need 3+ years of professional experience.</p>", (3.0, None)),
        ("<ul><li>2-4 years of experience in games</li></ul>", (2.0, 4.0)),
        ("<p>We have been making games for 10 years.</p>", (None, None)),
        ("<p>5+ years of Unreal experience preferred.</p>", (None, None)),
    ],
)
def test_years_are_read_from_the_rendered_text(
    description: str,
    expected: tuple[float | None, float | None],
) -> None:
    """The rules run on plain text, so the HTML has to be rendered first."""
    normalized = normalize_listing(make_job_listing(description_raw=description))

    assert (normalized.years_required_min, normalized.years_required_max) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("remote", WorkplaceType.REMOTE),
        ("unspecified", WorkplaceType.UNKNOWN),
        ("flexible", WorkplaceType.UNKNOWN),
        (None, WorkplaceType.UNKNOWN),
    ],
)
def test_the_source_workplace_type_flows_through(raw: Any, expected: WorkplaceType) -> None:
    normalized = normalize_listing(make_job_listing(workplace_type_raw=raw))

    assert normalized.workplace_type is expected
