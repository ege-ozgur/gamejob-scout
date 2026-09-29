"""HTML to plain text, including the traps that make the naive version wrong."""

import pytest

from gamejob_scout.normalization import to_plain_text

GREENHOUSE_SHAPE = (
    "<p><strong>About the role</strong></p>"
    "<p>You will build gameplay systems in C++ and work on tools &amp; pipelines.</p>"
)
LEVER_SHAPE = (
    "<div>We are looking for a Gameplay Programmer.</div>"
    "<section><h3>Responsibilities</h3><ul>\n<li>Build gameplay systems</li>\n"
    "<li>Profile hot paths</li></ul></section>"
    "<div>We review every application.</div>"
)


def test_words_never_run_together() -> None:
    """`BeautifulSoup.get_text()` alone yields 'About the roleYou will build'."""
    text = to_plain_text(GREENHOUSE_SHAPE)

    assert text is not None
    assert "roleYou" not in text
    assert text.startswith("About the role")
    assert "You will build gameplay systems" in text


def test_every_list_item_gets_its_own_line() -> None:
    text = to_plain_text(LEVER_SHAPE)

    assert text is not None
    lines = [line for line in text.splitlines() if line]
    assert "Build gameplay systems" in lines
    assert "Profile hot paths" in lines


def test_entities_are_decoded_exactly_once() -> None:
    text = to_plain_text(GREENHOUSE_SHAPE)

    assert text is not None
    assert "tools & pipelines" in text
    assert "&amp;" not in text


def test_is_not_idempotent_and_must_not_be_claimed_to_be() -> None:
    """Pins the counterexample so the claim cannot creep back into the docs.

    Entity decoding runs one way only, which is why normalization always starts
    from the stored description_raw rather than from its own earlier output.
    """
    once = to_plain_text("&lt;b&gt;Hi&lt;/b&gt;")
    assert once == "<b>Hi</b>"

    twice = to_plain_text(once or "")
    assert twice == "Hi"
    assert twice != once


@pytest.mark.parametrize("tag", ["script", "style", "noscript"])
def test_non_content_tags_are_dropped(tag: str) -> None:
    text = to_plain_text(f"<p>Real words.</p><{tag}>SECRETJUNK</{tag}>")

    assert text is not None
    assert "SECRETJUNK" not in text
    assert "Real words." in text


def test_comments_are_dropped() -> None:
    text = to_plain_text("<p>Visible.</p><!-- HIDDENNOTE -->")

    assert text == "Visible."


def test_whitespace_is_collapsed() -> None:
    text = to_plain_text("<p>Too      many\t\tspaces</p>")

    assert text == "Too many spaces"


def test_blank_lines_never_pile_up() -> None:
    text = to_plain_text("<div><p>One</p></div><div><div><p>Two</p></div></div>")

    assert text is not None
    assert "\n\n\n" not in text


@pytest.mark.parametrize("markup", ["", "   ", "<div></div>", "<p><span></span></p>", "<br>"])
def test_markup_without_words_is_none(markup: str) -> None:
    assert to_plain_text(markup) is None


def test_br_breaks_a_line() -> None:
    assert to_plain_text("Alpha<br>Beta") == "Alpha\nBeta"


def test_inline_tags_do_not_break_a_line() -> None:
    """A <strong> inside a sentence must not split it."""
    assert to_plain_text("<p>Work on <strong>gameplay</strong> systems</p>") == (
        "Work on gameplay systems"
    )
