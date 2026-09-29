"""Location tidying, and the Turkish casing trap that makes it necessary."""

import pytest

from gamejob_scout.normalization import clean_location, fold


def test_the_case_str_lower_gets_wrong() -> None:
    """`"İstanbul".lower()` is 'i̇stanbul' — an i plus a combining dot.

    A real Greenhouse board carried both spellings on different postings, so
    without folding they would never group together.
    """
    assert "İstanbul".lower() != "istanbul"
    assert fold("İstanbul") == fold("Istanbul") == "istanbul"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Kadıköy", "Kadikoy"),
        ("Sarıyer", "Sariyer"),
        ("Şişli", "Sisli"),
        ("İzmir", "Izmir"),
        ("Türkiye", "Turkiye"),
        ("Gaziantep", "GAZİANTEP"),
    ],
)
def test_turkish_spellings_fold_together(left: str, right: str) -> None:
    assert fold(left) == fold(right)


def test_folding_is_case_and_space_insensitive() -> None:
    assert fold("  İSTANBUL  ") == fold("istanbul")


def test_both_istanbul_spellings_canonicalise_the_same_way() -> None:
    assert clean_location("Sarıyer, Istanbul") == "Sarıyer, İstanbul"
    assert clean_location("Sarıyer, İstanbul") == "Sarıyer, İstanbul"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("istanbul", "İstanbul"),
        ("ISTANBUL", "İstanbul"),
        ("Izmir", "İzmir"),
        ("turkey", "Türkiye"),
        ("Turkiye", "Türkiye"),
        ("Kadıköy, Istanbul, Turkey", "Kadıköy, İstanbul, Türkiye"),
    ],
)
def test_known_names_reach_one_canonical_spelling(raw: str, expected: str) -> None:
    assert clean_location(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["Remote - Europe", "Sarıyer", "London", "Anywhere in EMEA", "Kadıköy"],
)
def test_unknown_parts_are_left_exactly_as_written(raw: str) -> None:
    """The alias table is an allowlist, so it can never mangle a name it does not know."""
    assert clean_location(raw) == raw


def test_whitespace_is_collapsed_and_separators_regularised() -> None:
    assert clean_location("  Kadıköy   ,    Istanbul  ") == "Kadıköy, İstanbul"


@pytest.mark.parametrize("raw", [None, "", "   ", ",", " , , "])
def test_nothing_usable_becomes_none(raw: str | None) -> None:
    assert clean_location(raw) is None


def test_cleaning_is_stable_when_applied_again() -> None:
    once = clean_location("Sarıyer, Istanbul")
    assert once is not None
    assert clean_location(once) == once
