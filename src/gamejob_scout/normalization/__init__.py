"""Deterministic normalization.

Collectors record what a company published; this package decides what it means,
using explicit vocabularies and no LLM. Every rule prefers ``UNKNOWN`` over a
guess, because these values feed an eligibility filter where a wrong answer
silently removes a job the candidate could have had.
"""

from gamejob_scout.normalization.experience import (
    LEVEL_TOKENS,
    find_years_required,
    resolve_experience_level,
)
from gamejob_scout.normalization.jobs import normalize_listing
from gamejob_scout.normalization.locations import CITY_ALIASES, clean_location, fold
from gamejob_scout.normalization.text import to_plain_text
from gamejob_scout.normalization.workplace import RECOGNISED_RAW, resolve_workplace_type

__all__ = [
    "CITY_ALIASES",
    "LEVEL_TOKENS",
    "RECOGNISED_RAW",
    "clean_location",
    "find_years_required",
    "fold",
    "normalize_listing",
    "resolve_experience_level",
    "resolve_workplace_type",
    "to_plain_text",
]
