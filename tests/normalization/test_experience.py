"""Seniority from a title, and required years from a description.

Both rules exist to say "I don't know" often. These values feed an eligibility
filter, where a wrong answer silently removes a job the candidate could have had.
"""

import pytest

from gamejob_scout.domain import ExperienceLevel
from gamejob_scout.normalization import find_years_required, resolve_experience_level

# -- experience level ------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Junior Technical Artist", ExperienceLevel.ENTRY),
        ("Jr. Gameplay Programmer", ExperienceLevel.ENTRY),
        ("Graduate Software Engineer", ExperienceLevel.ENTRY),
        ("Associate Producer", ExperienceLevel.ENTRY),
        ("Gameplay Programmer, Entry Level", ExperienceLevel.ENTRY),
        ("Senior Gameplay Programmer", ExperienceLevel.SENIOR),
        ("Sr Engine Programmer", ExperienceLevel.SENIOR),
        ("Principal Rendering Engineer", ExperienceLevel.LEAD),
        ("Staff Engineer", ExperienceLevel.LEAD),
        ("Head of Engineering", ExperienceLevel.LEAD),
        ("Mid-Level Gameplay Programmer", ExperienceLevel.MID),
        ("Gameplay Programming Intern", ExperienceLevel.INTERNSHIP),
    ],
)
def test_a_single_signal_resolves(title: str, expected: ExperienceLevel) -> None:
    assert resolve_experience_level(title) == expected


def test_new_grad_is_one_signal_not_two() -> None:
    """This title carries an ENTRY word and nothing from any other level."""
    assert resolve_experience_level("Software Engineer, Games (New Grad)") == ExperienceLevel.ENTRY


@pytest.mark.parametrize(
    "title",
    [
        "Senior/Lead Technical Artist",
        "Junior to Mid-Level Gameplay Programmer",
        "Senior Staff Engineer",
        "Intern or Junior Artist",
    ],
)
def test_two_levels_in_one_title_yield_unknown(title: str) -> None:
    """Picking one of two contradictory signals would be inventing information."""
    assert resolve_experience_level(title) == ExperienceLevel.UNKNOWN


@pytest.mark.parametrize(
    "title",
    ["Gameplay Programmer", "Technical Artist", "Producer", "Oyun Programcısı", ""],
)
def test_no_signal_is_unknown(title: str) -> None:
    assert resolve_experience_level(title) == ExperienceLevel.UNKNOWN


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Kıdemli Oyun Programcısı", ExperienceLevel.SENIOR),
        ("Stajyer Oyun Programcısı", ExperienceLevel.INTERNSHIP),
        ("Stajyeri Aranıyor", ExperienceLevel.INTERNSHIP),
        ("Yeni Mezun Yazılım Mühendisi", ExperienceLevel.ENTRY),
    ],
)
def test_turkish_titles_match_on_their_stems(title: str, expected: ExperienceLevel) -> None:
    """Turkish is agglutinative: `\\bstajyer\\b` would miss `Stajyeri`."""
    assert resolve_experience_level(title) == expected


def test_a_turkish_stem_is_not_allowed_to_be_too_greedy() -> None:
    """`kıdemsiz` means *non*-senior — `-siz` is the privative suffix.

    This is why the SENIOR token is the whole word `kıdemli` rather than the
    shorter stem `kıdem`: matching `kıdem\\w*` would make a word and its exact
    opposite resolve to the same level.
    """
    assert resolve_experience_level("Kıdemsiz Oyun Programcısı") == ExperienceLevel.UNKNOWN


def test_a_level_word_inside_another_word_does_not_count() -> None:
    """'Midfielder' is not a mid-level role, and 'Leadership' is not a lead role."""
    assert resolve_experience_level("Midfielder Simulation Engineer") == ExperienceLevel.UNKNOWN
    assert resolve_experience_level("Leadership Coach") == ExperienceLevel.UNKNOWN


# -- years required --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Strong C++ and 3+ years of professional experience.", (3.0, None)),
        ("2-4 years of experience with gameplay systems.", (2.0, 4.0)),
        # The literal en dash is this case's whole point: it sits directly below
        # the hyphen case so the two are compared side by side.
        ("2–4 years of experience with gameplay systems.", (2.0, 4.0)),  # noqa: RUF001
        ("2 to 4 years of experience with gameplay systems.", (2.0, 4.0)),
        ("At least 3 years of experience.", (3.0, None)),
        ("Minimum 5 years of relevant experience.", (5.0, None)),
        ("En az 3 yıl oyun geliştirme deneyimi.", (3.0, None)),
        ("3 yıl deneyimi olan adaylar.", (3.0, None)),
    ],
)
def test_a_stated_requirement_is_read(text: str, expected: tuple[float, float | None]) -> None:
    assert find_years_required(text) == expected


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("We have been making games for 10 years.", "company history"),
        ("Founded 12 years ago in İstanbul.", "company history"),
        ("Our studio has shipped titles since 2010, 15 years of hits.", "company history"),
        ("Enjoy 3 years of paid parental leave.", "benefit"),
        ("Unlimited vacation after 2 years of service.", "benefit"),
        ("No prior years of experience required.", "negation"),
        ("Experience without 5 years in AAA is fine.", "negation"),
        ("5+ years of Unreal experience preferred.", "preference"),
        ("3 years of C++ experience is nice to have.", "preference"),
        ("Ideally 4 years of experience.", "preference"),
        ("4 yıl deneyim tercihen.", "preference"),
    ],
)
def test_a_number_beside_years_is_not_automatically_a_requirement(text: str, why: str) -> None:
    """The field is called years_required, so it records requirements only."""
    assert find_years_required(text) == (None, None), why


@pytest.mark.parametrize(
    "text",
    [
        "Up to 3 years of experience required.",
        "Less than 5 years of experience.",
        "Fewer than 2 years of experience is fine.",
        "No more than 4 years of experience.",
        "At most 6 years of experience.",
        "A maximum of 3 years of experience.",
        "Maximum 3 years of experience.",
        "Under 3 years of experience.",
        "En fazla 3 yıl deneyim.",
    ],
)
def test_an_upper_bound_is_not_a_minimum(text: str) -> None:
    """ "Up to 3 years" caps the figure; it does not demand it.

    Reading the 3 as a requirement would invent a bar the posting never set,
    and in an eligibility filter that quietly removes jobs the candidate
    qualifies for.
    """
    assert find_years_required(text) == (None, None)


@pytest.mark.parametrize(
    "text",
    [
        "3 years of experience or less.",
        "3 years of experience or fewer.",
        "3 years of experience or below.",
        "5 years of experience max.",
        "3 yıl veya daha az deneyim.",
    ],
)
def test_an_upper_bound_after_the_number_is_caught_too(text: str) -> None:
    """The capping wording does not have to come first to mean the same thing."""
    assert find_years_required(text) == (None, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Between 2 and 4 years of experience required.", (2.0, 4.0)),
        ("Between 3 and 5 years of experience.", (3.0, 5.0)),
        ("2 ile 4 yıl arası deneyim.", (2.0, 4.0)),
    ],
)
def test_a_between_range_reads_as_a_range(
    text: str,
    expected: tuple[float, float],
) -> None:
    """The upper number must never be reported as the minimum.

    "Between 2 and 4 years" used to return (4.0, None), which claimed the
    posting demanded four years when it asked for two.
    """
    assert find_years_required(text) == expected


def test_and_only_joins_a_range_when_it_really_separates_two_numbers() -> None:
    """Two separate requirements joined by "and" are still two requirements.

    The first number is followed by "years", not by "and", so the range form
    cannot fire — and the two candidates then disagree, giving nothing.
    """
    text = "3 years of C++ experience and 5 years of Unity experience."

    assert find_years_required(text) == (None, None)


def test_a_range_needs_whitespace_around_the_word_separator() -> None:
    """ "2and4" is not a range, so it must not be read as one."""
    assert find_years_required("2and4 years of experience.") == (None, None)


@pytest.mark.parametrize(
    "text",
    [
        "Our team has 20 years of experience in games.",
        "Our studio has 15 years of experience.",
        "Our people bring 12 years of experience.",
        "Between us we have 40 years of experience.",
        "We have 30 years of combined experience.",
    ],
)
def test_years_belonging_to_the_company_are_not_a_requirement(text: str) -> None:
    """The experience is the studio's, not something asked of the candidate."""
    assert find_years_required(text) == (None, None)


def test_a_genuine_requirement_phrased_with_we_have_still_counts() -> None:
    """The company-description phrases are narrow on purpose.

    Blocking every "we have" would lose this, which is a real requirement.
    """
    text = "We have an opening for someone with 3+ years of experience."

    assert find_years_required(text) == (3.0, None)


def test_requirements_that_agree_across_lines_collapse() -> None:
    text = "3+ years of experience with C++.\nWe expect 3+ years of experience overall."

    assert find_years_required(text) == (3.0, None)


def test_requirements_that_disagree_yield_nothing() -> None:
    """Both may genuinely apply; reporting the smaller is presenting a guess as fact."""
    text = "3+ years of C++ experience.\n5+ years of leadership experience."

    assert find_years_required(text) == (None, None)


@pytest.mark.parametrize("text", [None, "", "   ", "No numbers here at all."])
def test_nothing_to_find_is_none(text: str | None) -> None:
    assert find_years_required(text) == (None, None)


@pytest.mark.parametrize("years", [61, 99])
def test_implausible_values_are_discarded(years: int) -> None:
    assert find_years_required(f"{years}+ years of experience.") == (None, None)


def test_a_reversed_range_is_discarded() -> None:
    assert find_years_required("Between 9-2 years of experience.") == (None, None)


def test_the_requirement_must_share_a_line_with_the_experience_word() -> None:
    """A years figure on its own line is not attached to anything."""
    text = "We want 10 years.\nExperience with gameplay systems is essential."

    assert find_years_required(text) == (None, None)
