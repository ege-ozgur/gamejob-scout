"""Configuration is validated up front, so a bad value fails where it is set."""

from dataclasses import fields
from typing import Any

import pytest

from gamejob_scout.http import HttpConfig
from tests.http.conftest import make_config

TIMEOUT_FIELDS = ["connect_timeout", "read_timeout", "write_timeout", "pool_timeout"]
NUMERIC_FIELDS = [
    *TIMEOUT_FIELDS,
    "requests_per_second",
    "max_attempts",
    "base_backoff_seconds",
    "max_backoff_seconds",
    "max_retry_after_seconds",
    "max_crawl_delay_seconds",
    "max_redirects",
]
NOT_A_NUMBER = [0, -1, float("nan"), float("inf")]


def test_a_valid_config_is_accepted() -> None:
    assert make_config().max_attempts == 3


@pytest.mark.parametrize("user_agent", ["", "   ", "gamejob-scout/0.1"])
def test_user_agent_must_identify_us(user_agent: str) -> None:
    with pytest.raises(ValueError, match="user_agent"):
        make_config(user_agent=user_agent)


@pytest.mark.parametrize("user_agent", ["bot (+ftp://example.com)", "bot (+http://)"])
def test_user_agent_url_must_be_a_real_http_url(user_agent: str) -> None:
    with pytest.raises(ValueError, match="user_agent"):
        make_config(user_agent=user_agent)


@pytest.mark.parametrize("name", TIMEOUT_FIELDS)
@pytest.mark.parametrize("value", NOT_A_NUMBER)
def test_timeouts_must_be_positive_and_finite(name: str, value: float) -> None:
    with pytest.raises(ValueError, match=name):
        make_config(**{name: value})


@pytest.mark.parametrize("value", NOT_A_NUMBER)
def test_requests_per_second_must_be_positive_and_finite(value: float) -> None:
    with pytest.raises(ValueError, match="requests_per_second"):
        make_config(requests_per_second=value)


@pytest.mark.parametrize("value", [0, -1])
def test_max_attempts_must_allow_at_least_one_try(value: int) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        make_config(max_attempts=value)


def test_one_attempt_means_no_retries() -> None:
    assert make_config(max_attempts=1).max_attempts == 1


@pytest.mark.parametrize(
    "name",
    ["base_backoff_seconds", "max_retry_after_seconds", "max_crawl_delay_seconds"],
)
def test_non_negative_timings(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        make_config(**{name: -1.0})
    assert getattr(make_config(**{name: 0.0}), name) == 0.0


def test_max_backoff_cannot_be_below_base_backoff() -> None:
    with pytest.raises(ValueError, match="max_backoff_seconds"):
        make_config(base_backoff_seconds=5.0, max_backoff_seconds=1.0)


def test_equal_backoff_bounds_are_fine() -> None:
    assert make_config(base_backoff_seconds=2.0, max_backoff_seconds=2.0).max_backoff_seconds == 2.0


def test_max_redirects_may_be_zero_but_not_negative() -> None:
    assert make_config(max_redirects=0).max_redirects == 0
    with pytest.raises(ValueError, match="max_redirects"):
        make_config(max_redirects=-1)


@pytest.mark.parametrize("name", NUMERIC_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_booleans_are_not_numbers(name: str, value: bool) -> None:
    """bool subclasses int, so max_attempts=True would silently mean 1."""
    with pytest.raises(ValueError, match=name):
        make_config(**{name: value})


@pytest.mark.parametrize("name", ["max_attempts", "max_redirects"])
def test_counts_must_be_integers(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        make_config(**{name: 2.5})


def test_documented_defaults() -> None:
    config = make_config()
    expected: dict[str, Any] = {
        "connect_timeout": 5.0,
        "read_timeout": 20.0,
        "write_timeout": 10.0,
        "pool_timeout": 5.0,
        "requests_per_second": 1.0,
        "max_attempts": 3,
        "base_backoff_seconds": 1.0,
        "max_backoff_seconds": 30.0,
        "max_retry_after_seconds": 60.0,
        "max_crawl_delay_seconds": 60.0,
        "max_redirects": 5,
    }
    for name, value in expected.items():
        assert getattr(config, name) == value


def test_base_interval_follows_the_rate() -> None:
    assert make_config(requests_per_second=2.0).base_interval_seconds == 0.5


def test_robots_compliance_cannot_be_switched_off() -> None:
    assert "respect_robots" not in {field.name for field in fields(HttpConfig)}
