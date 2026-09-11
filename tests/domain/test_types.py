"""Shared types, and the conventions every domain model follows.

The per-model rules live in the other test modules. These tests cover the pieces
that are supposed to behave identically everywhere: cleaning up string lists,
converting datetimes to UTC, immutability, rejecting unknown fields, and
round-tripping through JSON.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from gamejob_scout.domain import dedupe_preserving_order, require_content, to_utc
from tests.factories import (
    make_candidate_profile,
    make_company,
    make_job_listing,
    make_run_report,
    make_source_result,
)

ALL_BUILDERS: list[Callable[[], BaseModel]] = [
    make_candidate_profile,
    make_company,
    make_job_listing,
    make_source_result,
    make_run_report,
]


def test_to_utc_converts_an_offset_datetime() -> None:
    istanbul = timezone(timedelta(hours=3))
    converted = to_utc(datetime(2026, 9, 11, 13, 0, tzinfo=istanbul))

    assert converted == datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    assert converted.tzinfo is UTC


def test_to_utc_leaves_utc_alone() -> None:
    already_utc = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)

    assert to_utc(already_utc) == already_utc


def test_require_content_returns_the_value_untouched() -> None:
    padded = " \n<div>Role</div>\t "

    assert require_content(padded) == padded


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_require_content_rejects_blanks(blank: str) -> None:
    with pytest.raises(ValueError, match="blank or whitespace only"):
        require_content(blank)


def test_dedupe_strips_drops_empties_and_removes_case_insensitive_duplicates() -> None:
    assert dedupe_preserving_order(["Python", " python ", "", "   ", "C++", "PYTHON"]) == (
        "Python",
        "C++",
    )


def test_dedupe_keeps_the_first_spelling_and_the_original_order() -> None:
    assert dedupe_preserving_order(["Unreal Engine", "unity", "UNREAL ENGINE", "Unity"]) == (
        "Unreal Engine",
        "unity",
    )


def test_dedupe_of_nothing_is_empty() -> None:
    assert dedupe_preserving_order([]) == ()
    assert dedupe_preserving_order(["", "  "]) == ()


@pytest.mark.parametrize("build", ALL_BUILDERS)
def test_models_round_trip_through_json(build: Callable[[], BaseModel]) -> None:
    model = build()

    assert type(model).model_validate(model.model_dump(mode="json")) == model


@pytest.mark.parametrize("build", ALL_BUILDERS)
def test_models_reject_unknown_fields(build: Callable[[], BaseModel]) -> None:
    payload = build().model_dump(mode="json")
    payload["not_a_real_field"] = "surprise"

    with pytest.raises(ValidationError):
        type(build()).model_validate(payload)


@pytest.mark.parametrize("build", ALL_BUILDERS)
def test_models_are_frozen(build: Callable[[], BaseModel]) -> None:
    model = build()
    field_name = next(iter(type(model).model_fields))

    with pytest.raises(ValidationError):
        setattr(model, field_name, "anything")
