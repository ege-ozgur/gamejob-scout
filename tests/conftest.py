"""Guards that hold for every test in this project.

The README promises the suite runs with no internet access and no paid calls,
and the HTTP layer promises it never really sleeps. These two fixtures turn both
promises into something enforced rather than asserted: an accidental socket or a
real `time.sleep` fails the test that caused it, immediately and by name.
"""

import socket
import time
from collections.abc import Iterator
from typing import Any, NoReturn

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail loudly if anything tries to open a real connection."""

    def blocked(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError(
            "tests must not make real network connections; mock the transport instead",
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail loudly if any code under test calls time.sleep.

    Waiting is injected everywhere it happens, so a test that genuinely sleeps
    means a seam was missed. Note this catches calls that look up `time.sleep`
    when they run; a default argument bound at import time would not be caught,
    which is why the fetcher's waiting is injected rather than reached for.
    """

    def blocked(seconds: float) -> NoReturn:
        raise AssertionError(f"tests must not sleep for real (asked for {seconds}s)")

    monkeypatch.setattr(time, "sleep", blocked)
    yield
