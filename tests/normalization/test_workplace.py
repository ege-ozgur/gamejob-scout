"""Every rung of the workplace-type ladder, including the disagreements."""

import pytest

from gamejob_scout.domain import WorkplaceType
from gamejob_scout.normalization import resolve_workplace_type


def resolve(
    raw: str | None = None, title: str = "Gameplay Programmer", location: str | None = None
) -> WorkplaceType:
    return resolve_workplace_type(raw=raw, title=title, location_raw=location)


# -- rung 1: a recognised source value wins outright -----------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("remote", WorkplaceType.REMOTE),
        ("hybrid", WorkplaceType.HYBRID),
        ("onsite", WorkplaceType.ON_SITE),
        ("on-site", WorkplaceType.ON_SITE),
        ("on_site", WorkplaceType.ON_SITE),
        ("REMOTE", WorkplaceType.REMOTE),
        ("  Hybrid  ", WorkplaceType.HYBRID),
    ],
)
def test_a_recognised_raw_value_is_taken_at_its_word(raw: str, expected: WorkplaceType) -> None:
    assert resolve(raw=raw) == expected


def test_a_recognised_raw_value_beats_contradicting_text() -> None:
    """The company stated it; a job title does not get to overrule that."""
    assert resolve(raw="onsite", title="Remote Gameplay Programmer") == WorkplaceType.ON_SITE


# -- rung 2: 'unspecified' and friends defer to the text -------------------


@pytest.mark.parametrize("raw", ["unspecified", "UNSPECIFIED", "", "   ", None])
def test_saying_nothing_defers_to_the_text(raw: str | None) -> None:
    assert resolve(raw=raw, title="Remote Gameplay Programmer") == WorkplaceType.REMOTE


# -- rung 3: an unfamiliar value is not silently ignored -------------------


@pytest.mark.parametrize("raw", ["flexible", "wfh", "work-from-home", "anywhere", "office-first"])
def test_an_unfamiliar_raw_value_yields_unknown(raw: str) -> None:
    """It means the source said something we do not understand.

    Overriding an explicit statement with a guess from the title would be
    presumptuous, and returning UNKNOWN makes a new vocabulary visible instead
    of quietly papering over it.
    """
    assert resolve(raw=raw, title="Remote Gameplay Programmer") == WorkplaceType.UNKNOWN


# -- text signals ----------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "location", "expected"),
    [
        ("Gameplay Programmer", "Remote - Europe", WorkplaceType.REMOTE),
        ("Remote Gameplay Programmer", None, WorkplaceType.REMOTE),
        ("Gameplay Programmer (Hybrid)", None, WorkplaceType.HYBRID),
        ("Gameplay Programmer", "İstanbul (Hybrid)", WorkplaceType.HYBRID),
        ("Gameplay Programmer", "On-site, İstanbul", WorkplaceType.ON_SITE),
        ("Uzaktan Oyun Programcısı", None, WorkplaceType.REMOTE),
        ("Oyun Programcısı", "Hibrit, İstanbul", WorkplaceType.HYBRID),
    ],
)
def test_explicit_words_are_read_from_title_and_location(
    title: str,
    location: str | None,
    expected: WorkplaceType,
) -> None:
    assert resolve(title=title, location=location) == expected


@pytest.mark.parametrize("location", ["Kadıköy, İstanbul", "İzmir", "London", "Sarıyer"])
def test_a_city_name_alone_never_implies_on_site(location: str) -> None:
    """That role may perfectly well be hybrid; nobody said otherwise."""
    assert resolve(location=location) == WorkplaceType.UNKNOWN


def test_a_remote_title_in_a_city_is_remote_not_a_conflict() -> None:
    """A city is not a competing signal — remote-from-İstanbul is a real thing."""
    assert resolve(title="Remote Gameplay Programmer", location="Kadıköy, İstanbul") == (
        WorkplaceType.REMOTE
    )


def test_title_and_location_disagreeing_yields_unknown() -> None:
    """Two contradictory statements are no reason to prefer one of them."""
    assert resolve(title="Remote Gameplay Programmer", location="Hybrid, İstanbul") == (
        WorkplaceType.UNKNOWN
    )


def test_a_title_carrying_two_signals_yields_unknown() -> None:
    assert resolve(title="Remote or On-site Gameplay Programmer") == WorkplaceType.UNKNOWN


def test_no_signal_anywhere_is_unknown() -> None:
    assert resolve() == WorkplaceType.UNKNOWN


def test_the_description_is_never_consulted() -> None:
    """'We are not a remote company' would otherwise flip the job."""
    assert "description" not in resolve_workplace_type.__code__.co_varnames
