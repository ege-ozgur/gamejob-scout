"""Proof that the offline guards in conftest are actually switched on.

Without these, a broken guard would silently stop protecting anything and the
suite would still look green.
"""

import socket
import time

import pytest


def test_opening_a_socket_fails_the_test() -> None:
    with pytest.raises(AssertionError, match="real network connections"):
        socket.create_connection(("example.com", 80))


def test_connecting_an_existing_socket_fails_the_test() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:  # noqa: SIM117
        with pytest.raises(AssertionError, match="real network connections"):
            sock.connect(("example.com", 80))


def test_sleeping_for_real_fails_the_test() -> None:
    with pytest.raises(AssertionError, match="must not sleep for real"):
        time.sleep(0.01)
