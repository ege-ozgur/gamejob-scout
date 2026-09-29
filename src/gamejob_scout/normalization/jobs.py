"""Turning a collected listing into a normalized one.

Collectors store what the company published. This module adds our reading of it:
plain text, a tidied location, and the enums the matcher speaks. Every derived
field sits outside ``HASHED_FIELDS``, so sharpening these rules later never makes
a stored job look edited.
"""

from gamejob_scout.domain import JobListing
from gamejob_scout.normalization.experience import find_years_required, resolve_experience_level
from gamejob_scout.normalization.locations import clean_location
from gamejob_scout.normalization.text import to_plain_text
from gamejob_scout.normalization.workplace import resolve_workplace_type

__all__ = ["normalize_listing"]


def normalize_listing(listing: JobListing) -> JobListing:
    """Return a new listing with the derived fields filled in.

    Pure: the input is untouched, and every run reads the same stored source
    truth, which is what makes ``normalize_listing(normalize_listing(x))`` equal
    ``normalize_listing(x)``.

    Going back through ``model_validate`` rather than ``model_copy`` re-runs the
    identity and hash checks on the way out. Since nothing derived is hashed, the
    hash has to come out unchanged — and if it ever does not, this raises instead
    of quietly storing a wrong one.
    """
    description_text = to_plain_text(listing.description_raw)
    years_min, years_max = find_years_required(description_text)

    derived = {
        "description_text": description_text,
        "location": clean_location(listing.location_raw),
        "workplace_type": resolve_workplace_type(
            raw=listing.workplace_type_raw,
            title=listing.title,
            location_raw=listing.location_raw,
        ),
        "experience_level": resolve_experience_level(listing.title),
        "years_required_min": years_min,
        "years_required_max": years_max,
    }
    return JobListing.model_validate({**listing.model_dump(mode="json"), **derived})
