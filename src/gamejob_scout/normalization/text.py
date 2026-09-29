"""Turning a posting's HTML into readable plain text.

The obvious approach does not work. ``BeautifulSoup(html).get_text()`` returns
``"About the roleYou will build gameplay systems"`` for a real posting: block
elements carry no text of their own, so the words on either side of them are
concatenated. The walk below inserts the line breaks that the markup implied.

This is deliberately **not** idempotent, and nothing should claim otherwise.
``to_plain_text("&lt;b&gt;Hi&lt;/b&gt;")`` returns ``"<b>Hi</b>"`` — the entities
decode to markup — and feeding that back in returns ``"Hi"``. Entity decoding
only runs one way, which is exactly why normalization always starts from the
stored ``description_raw`` rather than from a value it produced earlier.
"""

import re
from typing import Final

from bs4 import BeautifulSoup, Comment, Tag
from bs4.element import NavigableString  # not re-exported from bs4 itself

__all__ = ["to_plain_text"]

_BLOCK_TAGS: Final[frozenset[str]] = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dd",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    },
)
"""Elements that enclose content, so text breaks on both sides of them."""

_BREAK_TAGS: Final[frozenset[str]] = frozenset({"br", "hr"})
"""Void elements that *are* a break. Wrapping these would double every one."""

_DROPPED_TAGS: Final[frozenset[str]] = frozenset({"script", "style", "noscript", "template"})

_INLINE_WHITESPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def to_plain_text(html: str) -> str | None:
    """Render a posting's HTML as plain text, or ``None`` if it carries no words.

    Entities are decoded exactly once, by the parser. Block elements become line
    breaks so that words never run together, and no punctuation is invented: no
    bullet markers, no headings decoration. The line structure the company wrote
    is preserved and nothing is added to it.
    """
    soup = BeautifulSoup(html, "html.parser")

    for element in soup.find_all(_DROPPED_TAGS):
        element.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    pieces: list[str] = []
    _collect(soup, pieces)

    lines = [_INLINE_WHITESPACE.sub(" ", line).strip() for line in "".join(pieces).split("\n")]
    text = _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    return text or None


def _collect(node: Tag, pieces: list[str]) -> None:
    """Walk the tree, emitting text and a newline around every block element."""
    for child in node.children:
        if isinstance(child, NavigableString):
            pieces.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue

        if child.name in _BREAK_TAGS:
            # A void element that *is* the break. Wrapping it the way a block is
            # wrapped would turn every single <br> into a paragraph gap.
            pieces.append("\n")
            continue

        block = child.name in _BLOCK_TAGS
        if block:
            pieces.append("\n")
        _collect(child, pieces)
        if block:
            pieces.append("\n")
