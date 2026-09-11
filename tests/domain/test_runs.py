"""Per-source outcomes and the run report that summarizes them."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from gamejob_scout.domain import RunReport, RunStatus, SourceResult
from tests.factories import (
    RUN_FINISHED_AT,
    RUN_STARTED_AT,
    make_failed_source,
    make_run_report,
    make_skipped_source,
    make_source_result,
)


def make_partial_source(**overrides: object) -> SourceResult:
    defaults: dict[str, object] = {
        "status": RunStatus.PARTIAL,
        "warnings": ("2 postings could not be parsed",),
    }
    return make_source_result(**{**defaults, **overrides})


# --- SourceResult -----------------------------------------------------------


def test_a_successful_source_is_valid() -> None:
    result = make_source_result()

    assert result.status is RunStatus.SUCCESS
    assert result.duration_seconds == 300.0


def test_duration_is_zero_for_an_instant_source() -> None:
    result = make_source_result(finished_at=RUN_STARTED_AT)

    assert result.duration_seconds == 0.0


def test_derived_values_are_not_serialized() -> None:
    assert "duration_seconds" not in make_source_result().model_dump()


def test_finishing_before_starting_is_rejected() -> None:
    with pytest.raises(ValidationError, match="finished_at"):
        make_source_result(started_at=RUN_FINISHED_AT, finished_at=RUN_STARTED_AT)


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.SKIPPED])
def test_failure_and_skip_need_an_explanation(status: RunStatus) -> None:
    with pytest.raises(ValidationError, match="requires a message"):
        make_source_result(
            status=status,
            jobs_found=0,
            jobs_new=0,
            jobs_updated=0,
            jobs_unchanged=0,
        )


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.SKIPPED])
def test_failure_and_skip_cannot_report_jobs(status: RunStatus) -> None:
    with pytest.raises(ValidationError, match="counts to be zero"):
        make_source_result(status=status, message="something went wrong")


def test_success_cannot_carry_warnings() -> None:
    with pytest.raises(ValidationError, match="cannot carry warnings"):
        make_source_result(warnings=("one posting was skipped",))


def test_success_cannot_carry_a_message() -> None:
    with pytest.raises(ValidationError, match="cannot carry a message"):
        make_source_result(message="mostly fine")


def test_partial_is_valid_with_warnings_only() -> None:
    assert make_partial_source().status is RunStatus.PARTIAL


def test_partial_is_valid_with_a_message_only() -> None:
    """Pagination and persistence failures are not parse errors, but still partial."""
    result = make_source_result(
        status=RunStatus.PARTIAL,
        message="stopped after page 3: the board stopped responding",
    )

    assert result.status is RunStatus.PARTIAL
    assert result.warnings == ()


def test_partial_needs_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires warnings or a message"):
        make_source_result(status=RunStatus.PARTIAL)


def test_counts_cannot_exceed_what_was_found() -> None:
    with pytest.raises(ValidationError, match="cannot exceed jobs_found"):
        make_source_result(jobs_found=5, jobs_new=3, jobs_updated=2, jobs_unchanged=1)


def test_counts_may_add_up_exactly() -> None:
    result = make_source_result(jobs_found=6, jobs_new=1, jobs_updated=2, jobs_unchanged=3)

    assert result.jobs_found == 6


def test_counts_may_fall_short_when_postings_failed_to_parse() -> None:
    result = make_partial_source(jobs_found=10, jobs_new=1, jobs_updated=0, jobs_unchanged=7)

    assert result.jobs_found == 10


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ValidationError, match="jobs_new"):
        make_source_result(jobs_new=-1)


def test_a_blank_warning_is_rejected() -> None:
    with pytest.raises(ValidationError, match="warnings"):
        make_partial_source(warnings=("   ",))


# --- RunReport --------------------------------------------------------------


def test_totals_are_the_sum_of_the_sources() -> None:
    report = make_run_report(
        sources=(
            make_source_result(jobs_found=10, jobs_new=3, jobs_updated=2, jobs_unchanged=5),
            make_source_result(
                source_key="other-studio-lever",
                company_key="other-studio",
                jobs_found=4,
                jobs_new=1,
                jobs_updated=0,
                jobs_unchanged=3,
            ),
        ),
    )

    assert report.jobs_found == 14
    assert report.jobs_new == 4
    assert report.jobs_updated == 2
    assert report.jobs_unchanged == 8
    assert report.sources_succeeded == 2


def test_an_empty_run_has_no_totals() -> None:
    report = make_run_report(sources=())

    assert report.jobs_found == 0
    assert report.sources_succeeded == 0


def test_two_boards_from_one_company_are_allowed() -> None:
    report = make_run_report(
        sources=(
            make_source_result(source_key="example-studio-greenhouse"),
            make_source_result(source_key="example-studio-lever"),
        ),
    )

    assert report.sources_succeeded == 2


def test_the_same_board_cannot_appear_twice() -> None:
    with pytest.raises(ValidationError, match="duplicate source_key"):
        make_run_report(sources=(make_source_result(), make_source_result()))


def test_a_source_cannot_run_outside_the_run_window() -> None:
    with pytest.raises(ValidationError, match="outside the run"):
        make_run_report(
            sources=(make_source_result(finished_at=datetime(2026, 9, 11, 9, 0, tzinfo=UTC)),),
        )


def test_run_finishing_before_starting_is_rejected() -> None:
    with pytest.raises(ValidationError, match="finished_at"):
        make_run_report(started_at=RUN_FINISHED_AT, finished_at=RUN_STARTED_AT, sources=())


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        pytest.param((), RunStatus.SKIPPED, id="no-sources"),
        pytest.param((make_skipped_source(),), RunStatus.SKIPPED, id="all-skipped"),
        pytest.param((make_source_result(),), RunStatus.SUCCESS, id="all-success"),
        pytest.param((make_failed_source(),), RunStatus.FAILED, id="all-failed"),
        pytest.param(
            (make_source_result(), make_skipped_source()),
            RunStatus.SUCCESS,
            id="success-plus-skipped",
        ),
        pytest.param(
            (make_failed_source(), make_skipped_source()),
            RunStatus.FAILED,
            id="failed-plus-skipped",
        ),
        pytest.param(
            (make_source_result(), make_failed_source()),
            RunStatus.PARTIAL,
            id="mixed-success-and-failure",
        ),
        pytest.param((make_partial_source(),), RunStatus.PARTIAL, id="one-partial"),
        pytest.param(
            (make_partial_source(), make_skipped_source()),
            RunStatus.PARTIAL,
            id="partial-plus-skipped",
        ),
    ],
)
def test_run_status_ignores_skipped_sources(
    sources: tuple[SourceResult, ...],
    expected: RunStatus,
) -> None:
    assert make_run_report(sources=sources).status is expected


def test_status_and_totals_are_not_serialized() -> None:
    dumped = make_run_report().model_dump()

    assert "status" not in dumped
    assert "jobs_found" not in dumped
    assert "duration_seconds" not in dumped


def test_each_report_gets_its_own_run_id() -> None:
    first = make_run_report()
    second = make_run_report()

    assert isinstance(first.run_id, UUID)
    assert first.run_id != second.run_id


def test_the_run_id_survives_a_json_round_trip() -> None:
    report = make_run_report()
    dumped = report.model_dump(mode="json")

    assert isinstance(dumped["run_id"], str)
    assert RunReport.model_validate(dumped).run_id == report.run_id
