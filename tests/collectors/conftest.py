"""Fixtures for collector tests.

pytest scopes fixtures by directory, so the `router` and `clock` defined for the
HTTP tests are not visible here. Their underlying helpers are reusable though,
so this re-declares the two fixtures rather than duplicating the machinery.
"""

from collections.abc import Iterator

import pytest
import respx

from tests.http.conftest import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock
