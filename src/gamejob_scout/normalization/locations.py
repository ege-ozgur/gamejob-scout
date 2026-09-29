"""Tidying a posting's location, and comparing Turkish text safely.

Turkish breaks the usual assumption that ``str.lower()`` is enough to compare
two spellings. ``"İstanbul".lower()`` is ``'i̇stanbul'`` — nine characters, a
plain ``i`` followed by a combining dot above — which does **not** equal
``'istanbul'``. This is not hypothetical: one real Greenhouse board carried both
``"Sarıyer, Istanbul"`` and ``"Sarıyer, İstanbul"`` on different postings.

:func:`fold` is the answer, and it is used for comparison only. What gets stored
keeps its proper spelling.
"""

import re
import unicodedata
from typing import Final

__all__ = ["CITY_ALIASES", "clean_location", "fold"]

_WHITESPACE = re.compile(r"\s+")

_TURKISH_TO_ASCII: Final[dict[int, str]] = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    },
)


def fold(value: str) -> str:
    """A comparison key: accent-free, case-free, and safe for Turkish.

    Turkish letters are mapped explicitly before NFKD, because ``ı`` and ``İ``
    are distinct letters rather than decorated Latin ones — stripping combining
    marks alone would leave ``ı`` untouched and turn ``İ`` into ``i`` plus a
    stray mark.

    Never stored. Its only job is to let two spellings of the same place meet.
    """
    mapped = value.translate(_TURKISH_TO_ASCII)
    decomposed = unicodedata.normalize("NFKD", mapped)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WHITESPACE.sub(" ", without_marks).strip().casefold()


CITY_ALIASES: Final[dict[str, str]] = {
    # Turkey is the primary market, and its place names are exactly where the
    # two-spelling problem shows up. Keys are folded; values are the canonical
    # spelling we store.
    "istanbul": "İstanbul",
    "izmir": "İzmir",
    "ankara": "Ankara",
    "antalya": "Antalya",
    "bursa": "Bursa",
    "kocaeli": "Kocaeli",
    "eskisehir": "Eskişehir",
    "turkiye": "Türkiye",
    "turkey": "Türkiye",
}
"""A short allowlist, not a gazetteer.

Anything absent from it is kept exactly as the company wrote it, so this can
only ever canonicalise a name we have deliberately taught it — never mangle one
we have not.
"""


def clean_location(raw: str | None) -> str | None:
    """Collapse whitespace and canonicalise the place names we recognise.

    ``"Sarıyer, Istanbul"`` and ``"Sarıyer, İstanbul"`` both become
    ``"Sarıyer, İstanbul"``. ``"Remote - Europe"`` is untouched, because nothing
    in it is in the alias table.
    """
    if raw is None:
        return None

    parts = [_WHITESPACE.sub(" ", part).strip() for part in raw.split(",")]
    kept = [CITY_ALIASES.get(fold(part), part) for part in parts if part]
    return ", ".join(kept) or None
