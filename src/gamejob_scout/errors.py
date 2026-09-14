"""The root of every error this project raises on purpose.

Having one base class means the ingestion runner can catch everything we meant
to happen with a single `except`, while a genuine programming mistake still
escapes and gets noticed.
"""

__all__ = ["GameJobScoutError"]


class GameJobScoutError(Exception):
    """Base class for expected, actionable failures."""
