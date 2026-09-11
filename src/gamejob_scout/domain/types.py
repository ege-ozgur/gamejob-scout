"""Reusable annotated types and validators shared by the domain models.

These exist so that every model enforces the same rules the same way: a title and
a company name are "non-empty" in exactly the same sense, and every datetime in
the system is stored in UTC.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, StringConstraints


def to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC.

    Naive datetimes never reach this function: ``AwareDatetime`` rejects them
    first. Converting on the way in means every stored instant is directly
    comparable and renders identically, so content hashes stay stable.
    """
    return value.astimezone(UTC)


def require_content(value: str) -> str:
    """Reject a blank string while returning the original completely untouched.

    Used for text we store exactly as a source published it. Whitespace is only
    inspected to decide whether there is any content at all; the value that gets
    stored is the one that came in, including its leading and trailing
    whitespace, because that is part of what the source actually sent.
    """
    if not value.strip():
        raise ValueError("must not be blank or whitespace only")
    return value


def dedupe_preserving_order(values: Iterable[str]) -> tuple[str, ...]:
    """Clean up a list of free-text entries from a hand-maintained config file.

    Strips whitespace, drops empty entries, and drops case-insensitive
    duplicates while keeping the first occurrence with its original casing::

        ["Python", " python ", "C++", ""] -> ("Python", "C++")

    Duplicates are removed rather than rejected because these lists are written
    by hand, where a repeat is a typo rather than something worth failing a run
    over. Cases that indicate genuine confusion are rejected by the models
    themselves (an empty ``target_roles``, or a role listed as both wanted and
    excluded).
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
    return tuple(result)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""A string that is stripped first and must still have content afterwards."""

VerbatimStr = Annotated[str, AfterValidator(require_content)]
"""A non-blank string stored exactly as supplied, whitespace and all.

For text that belongs to the source rather than to us, such as a job
description. Any cleanup we apply would make it our output instead of theirs,
and would mean our own changes could alter a listing's content hash.
"""

UtcDatetime = Annotated[AwareDatetime, AfterValidator(to_utc)]
"""A timezone-aware datetime, normalized to UTC. Naive datetimes are rejected."""

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
"""A stable lowercase identifier such as ``dream-games``.

Invalid input is rejected rather than coerced, so ``"Dream Games"`` fails loudly
instead of two different spellings silently collapsing onto one key.
"""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A lowercase hexadecimal SHA-256 digest."""

StringTuple = Annotated[tuple[str, ...], AfterValidator(dedupe_preserving_order)]
"""An ordered, de-duplicated tuple of non-empty strings.

A tuple rather than a set: sets serialize in unpredictable order, which would
make hashes and test snapshots unstable.
"""
