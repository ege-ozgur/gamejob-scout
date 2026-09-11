"""Smoke test: the package is installed and importable, and reports a version.

This exists so the toolchain (pytest, mypy, ruff, CI) has something real to run
before any feature code is written.
"""

import gamejob_scout


def test_package_exposes_a_version() -> None:
    assert isinstance(gamejob_scout.__version__, str)
    assert gamejob_scout.__version__ != ""
