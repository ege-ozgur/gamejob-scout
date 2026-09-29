"""Reading seniority from a title, and required years from a description.

Both rules are built to say "I don't know" often. A wrong seniority or a wrong
years figure feeds an eligibility filter, where it quietly removes jobs the
candidate could have had.

Turkish needs stem matching rather than whole-word matching, because it is
agglutinative: ``deneyim`` appears as ``deneyimi``, ``deneyime``, ``deneyimli``,
and ``\\bdeneyim\\b`` matches none of them.
"""

import re
from typing import Final

from gamejob_scout.domain import ExperienceLevel
from gamejob_scout.normalization.locations import fold

__all__ = ["LEVEL_TOKENS", "find_years_required", "resolve_experience_level"]

LEVEL_TOKENS: Final[tuple[tuple[ExperienceLevel, tuple[str, ...]], ...]] = (
    (ExperienceLevel.INTERNSHIP, ("intern", "internship", "stajyer", "staj")),
    (
        ExperienceLevel.ENTRY,
        (
            "junior",
            "jr",
            "graduate",
            "grad",
            "new grad",
            "entry level",
            "entry-level",
            "associate",
            "yeni mezun",
        ),
    ),
    (ExperienceLevel.MID, ("mid", "mid-level", "midlevel", "mid level")),
    (ExperienceLevel.SENIOR, ("senior", "sr", "kıdemli")),
    (ExperienceLevel.LEAD, ("lead", "principal", "staff", "head of", "takım lideri")),
)
"""One reviewable table. Turkish entries are matched as stems, English as words."""

_TURKISH_STEMS: Final[frozenset[str]] = frozenset(
    {"stajyer", "staj", "kıdemli", "yeni mezun", "takım lideri"},
)


def _token_pattern(token: str) -> re.Pattern[str]:
    """Word boundaries for English; stem-plus-suffix for Turkish."""
    folded = re.escape(fold(token))
    suffix = r"\w*" if token in _TURKISH_STEMS else ""
    return re.compile(
        rf"(?<!\w){folded}{suffix}(?!\w)" if not suffix else rf"(?<!\w){folded}{suffix}"
    )


def resolve_experience_level(title: str) -> ExperienceLevel:
    """Read seniority from a job title, or return ``UNKNOWN``.

    The title only. Descriptions say things like "you will work with senior
    engineers", which describes colleagues rather than the role.

    Words from **more than one level** give ``UNKNOWN``: "Senior/Lead Technical
    Artist" and "Junior to Mid-Level Gameplay Programmer" genuinely carry two
    signals, and picking one would be inventing information.

    Note that "Software Engineer, Games (New Grad)" carries one signal, not two,
    and resolves to ``ENTRY``.
    """
    folded = fold(title)
    matched = {
        level
        for level, tokens in LEVEL_TOKENS
        if any(_token_pattern(token).search(folded) for token in tokens)
    }
    if len(matched) == 1:
        return matched.pop()
    return ExperienceLevel.UNKNOWN


_YEARS = re.compile(
    # \u2013 is an en dash, written escaped because a literal one is almost
    # indistinguishable from the hyphen sitting next to it in this alternation.
    #
    # Whitespace is required around the word separators but optional around the
    # punctuation ones, so "2 and 4 years" reads as a range while "2and4 years"
    # is not mistaken for one.
    r"(?<!\w)(\d{1,2})(?:\s*\+|(?:\s*[-\u2013]\s*|\s+(?:to|ile|and)\s+)(\d{1,2}))?"
    r"\s*(?:years?|yil\w*)(?!\w)",
)
"""A number beside a years word. Folded text, so ``yıl`` arrives as ``yil``."""

_EXPERIENCE = re.compile(r"(?<!\w)(?:experience|deneyim\w*|tecrube\w*)")
"""What separates a requirement from company history or a benefit."""

_DISQUALIFIERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "preference",
        (
            "preferred",
            "preferably",
            "nice to have",
            "bonus",
            "a plus",
            "ideally",
            "tercihen",
            "artı",
        ),
    ),
    ("negation", ("no ", "not ", "without", "gerekmez", "değil", "aranmaz")),
    (
        # An upper bound is not a minimum. "Up to 3 years of experience" caps
        # the figure rather than demanding it, so reading 3 as a requirement
        # would invent a bar the posting never set.
        #
        # The wording can also follow the number ("3 years of experience or
        # less"), so trailing forms are listed too.
        "upper bound",
        (
            "up to",
            "less than",
            "fewer than",
            "no more than",
            "at most",
            "under",
            "maximum",
            " max",
            "or less",
            "or fewer",
            "or below",
            "en fazla",
            "en çok",
            "veya daha az",
        ),
    ),
    (
        "company history",
        ("founded", "since", "we have been", "kuruldu", "yılından beri", "years ago"),
    ),
    (
        # The years belong to the company, not to the candidate. Deliberately
        # narrow phrases: "we have an opening for someone with 3+ years" is a
        # genuine requirement and must keep working.
        "company description",
        (
            "our team",
            "our studio",
            "our people",
            "combined experience",
            "collectively",
            "between us",
            "ekibimiz",
        ),
    ),
    ("benefit", ("leave", "vacation", "holiday", "izin", "tatil")),
)
"""Contexts in which a years figure is not a requirement on the candidate."""


def _is_requirement_line(folded_line: str) -> bool:
    if not _EXPERIENCE.search(folded_line):
        return False
    return not any(
        fold(marker) in folded_line for _, markers in _DISQUALIFIERS for marker in markers
    )


def find_years_required(text: str | None) -> tuple[float | None, float | None]:
    """Find the years of experience a posting *requires*.

    A number next to "years" is a weak signal by itself: job adverts use the
    phrasing for company history ("we have been making games for 10 years"),
    benefits ("3 years of paid parental leave"), negated requirements ("no prior
    years of experience required") and preferences ("5+ years preferred"). None
    of those is a requirement, so a line counts only when it carries a years
    quantity **and** an experience word **and** no disqualifying marker.

    Combining is deliberately unambitious. If every qualifying line agrees, that
    is the answer; if they disagree — "3+ years C++" beside "5+ years
    leadership" — the result is ``(None, None)``. Both requirements may genuinely
    apply, and reporting the smaller one would present a guess as a fact.
    """
    if not text:
        return (None, None)

    found: set[tuple[float, float | None]] = set()
    for line in text.splitlines():
        folded = fold(line)
        if not _is_requirement_line(folded):
            continue
        for match in _YEARS.finditer(folded):
            low = float(match.group(1))
            high = float(match.group(2)) if match.group(2) else None
            if not _in_range(low) or (high is not None and not _in_range(high)):
                continue
            if high is not None and low > high:
                continue
            found.add((low, high))

    if len(found) != 1:
        return (None, None)
    low, high = found.pop()
    return (low, high)


def _in_range(value: float) -> bool:
    return 0 <= value <= 60
