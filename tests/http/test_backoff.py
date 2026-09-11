"""Retry classification, backoff bounds, and Retry-After parsing."""

import random
from datetime import UTC, datetime

import pytest

from gamejob_scout.http import (
    RETRYABLE_STATUS,
    backoff_cap,
    backoff_delay,
    is_retryable_status,
    parse_retry_after,
)

NOW = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


def test_default_caps_match_the_two_retries_max_attempts_allows() -> None:
    """max_attempts=3 means one try plus two retries, so two waits: 1s then 2s."""
    caps = [backoff_cap(attempt, base_seconds=1.0, maximum_seconds=30.0) for attempt in (1, 2)]

    assert caps == [1.0, 2.0]


def test_the_ceiling_holds() -> None:
    assert backoff_cap(10, base_seconds=1.0, maximum_seconds=30.0) == 30.0


def test_an_absurd_attempt_number_does_not_overflow() -> None:
    assert backoff_cap(5000, base_seconds=1.0, maximum_seconds=30.0) == 30.0


def test_jitter_is_reproducible_and_inside_the_cap() -> None:
    first = [
        backoff_delay(a, base_seconds=1.0, maximum_seconds=30.0, rng=random.Random(12345))
        for a in (1, 2, 3)
    ]
    second = [
        backoff_delay(a, base_seconds=1.0, maximum_seconds=30.0, rng=random.Random(12345))
        for a in (1, 2, 3)
    ]

    assert first == second
    for attempt, delay in zip((1, 2, 3), first, strict=True):
        assert 0.0 <= delay <= backoff_cap(attempt, base_seconds=1.0, maximum_seconds=30.0)


def test_zero_base_means_no_wait() -> None:
    delay = backoff_delay(1, base_seconds=0.0, maximum_seconds=0.0, rng=random.Random(1))

    assert delay == 0.0


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS))
def test_retryable_statuses(status: int) -> None:
    assert is_retryable_status(status)


@pytest.mark.parametrize("status", [200, 301, 400, 401, 403, 404, 410, 422, 501, 505])
def test_permanent_statuses(status: int) -> None:
    assert not is_retryable_status(status)


@pytest.mark.parametrize(("raw", "expected"), [("5", 5.0), ("0", 0.0), ("120", 120.0)])
def test_delay_seconds_form(raw: str, expected: float) -> None:
    assert parse_retry_after(raw, now=NOW) == expected


def test_http_date_in_the_future() -> None:
    assert parse_retry_after("Fri, 11 Sep 2026 08:00:30 GMT", now=NOW) == 30.0


def test_http_date_in_the_past_never_goes_negative() -> None:
    assert parse_retry_after("Fri, 11 Sep 2026 07:59:00 GMT", now=NOW) == 0.0


@pytest.mark.parametrize(
    "raw",
    ["-5", "1.5", "NaN", "nan", "inf", "Infinity", "soon", "", "   ", "Fri, 99 Xxx 2026"],
)
def test_unusable_values_fall_back_to_backoff(raw: str) -> None:
    """Returning None is the signal for 'use exponential backoff instead'."""
    assert parse_retry_after(raw, now=NOW) is None
