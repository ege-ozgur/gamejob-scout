"""Rules for the candidate profile."""

import json

import pytest
from pydantic import ValidationError

from gamejob_scout.domain import CandidateProfile, Education, ExperienceLevel, WorkplaceType
from tests.factories import EXAMPLE_PROFILE_PATH, make_candidate_profile


def test_profile_carries_no_identity_field() -> None:
    """Matching never needs a name, and this model is sent to a language model."""
    assert "name" not in CandidateProfile.model_fields
    assert "display_name" not in CandidateProfile.model_fields
    assert "email" not in CandidateProfile.model_fields


def test_target_roles_must_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="target_roles"):
        make_candidate_profile(target_roles=[])


def test_target_roles_of_only_blanks_is_empty_and_rejected() -> None:
    with pytest.raises(ValidationError, match="target_roles"):
        make_candidate_profile(target_roles=["", "   "])


def test_duplicate_skills_are_removed_keeping_the_first_spelling() -> None:
    profile = make_candidate_profile(skills=["Debugging", " debugging ", "Profiling"])

    assert profile.skills == ("Debugging", "Profiling")


def test_a_role_cannot_be_both_targeted_and_excluded() -> None:
    with pytest.raises(ValidationError, match="targeted and excluded"):
        make_candidate_profile(
            target_roles=["Gameplay Programmer"],
            excluded_roles=["gameplay programmer"],
        )


def test_workplace_types_are_deduplicated_and_ordered() -> None:
    profile = make_candidate_profile(
        acceptable_workplace_types=[
            WorkplaceType.REMOTE,
            WorkplaceType.HYBRID,
            WorkplaceType.REMOTE,
        ],
    )

    assert profile.acceptable_workplace_types == (WorkplaceType.HYBRID, WorkplaceType.REMOTE)


def test_acceptable_workplace_types_must_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="acceptable_workplace_types"):
        make_candidate_profile(acceptable_workplace_types=[])


def test_default_workplace_types_accept_anything() -> None:
    profile = make_candidate_profile()

    assert profile.acceptable_workplace_types == (
        WorkplaceType.HYBRID,
        WorkplaceType.ON_SITE,
        WorkplaceType.REMOTE,
    )


@pytest.mark.parametrize("years", [0.0, 0.5, 60.0])
def test_years_of_experience_within_bounds(years: float) -> None:
    assert make_candidate_profile(years_of_experience=years).years_of_experience == years


@pytest.mark.parametrize("years", [-0.1, 60.1])
def test_years_of_experience_outside_bounds(years: float) -> None:
    with pytest.raises(ValidationError, match="years_of_experience"):
        make_candidate_profile(years_of_experience=years)


def test_experience_level_must_be_a_known_value() -> None:
    with pytest.raises(ValidationError, match="experience_level"):
        make_candidate_profile(experience_level="extremely senior")


def test_experience_level_accepts_its_string_value() -> None:
    profile = make_candidate_profile(experience_level="entry")

    assert profile.experience_level is ExperienceLevel.ENTRY


@pytest.mark.parametrize("year", [1949, 2101])
def test_graduation_year_outside_bounds(year: int) -> None:
    with pytest.raises(ValidationError, match="graduation_year"):
        Education(
            degree="MSc",
            field_of_study="Games Engineering",
            institution="Example University",
            graduation_year=year,
        )


def test_project_url_is_optional_but_must_be_valid_when_given() -> None:
    profile = make_candidate_profile(
        projects=[{"name": "Prototype", "summary": "A small prototype.", "url": None}],
    )
    assert profile.projects[0].url is None

    with pytest.raises(ValidationError, match="url"):
        make_candidate_profile(
            projects=[{"name": "Prototype", "summary": "A small prototype.", "url": "not a url"}],
        )


def test_example_profile_file_is_valid() -> None:
    """The committed example doubles as documentation, so it must stay loadable."""
    payload = json.loads(EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8"))
    profile = CandidateProfile.model_validate(payload)

    assert profile.target_roles
    assert profile.experience_level is ExperienceLevel.ENTRY
