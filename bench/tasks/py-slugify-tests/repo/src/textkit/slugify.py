"""Turn a title into a URL slug. The rules are in docs/SLUG_RULES.md.

>>> slugify("Fish & Chips: Don't Panic!")
'fish-and-chips-dont-panic'
>>> slugify("A Very Long Title For A Page", max_length=14)
'a-very-long'
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from textkit.translit import fold

SEPARATORS = ("-", "_")
#: Symbols that are read as words (rule 3).
SYMBOL_WORDS = {"&": " and ", "@": " at "}
#: Characters that are removed without leaving a gap (rule 4).
APOSTROPHES = "'\u2019\u2018`"

_WORD = re.compile(r"[a-z0-9]+")


def _check_options(separator: str, max_length: int | None) -> None:
    if separator not in SEPARATORS:
        raise ValueError(f"separator must be '-' or '_', not {separator!r}")
    if max_length is not None and max_length < 1:
        raise ValueError(f"max_length must be at least 1, not {max_length}")


def _truncate(slug: str, separator: str, max_length: int) -> str:
    """Cut ``slug`` to at most ``max_length`` characters, after a whole word if possible."""
    if len(slug) <= max_length:
        return slug
    if slug[max_length] == separator:
        return slug[:max_length]
    head = slug[:max_length]
    boundary = head.rfind(separator)
    return head[:boundary] if boundary > 0 else head


def slugify(
    text: str,
    *,
    separator: str = "-",
    max_length: int | None = None,
    stopwords: Iterable[str] = (),
) -> str:
    """The slug for ``text``: lowercase ASCII words joined by ``separator``.

    Args:
        text: The title.
        separator: ``-`` (the default) or ``_``.
        max_length: Longest slug to return; a longer slug is cut after the last whole word
            that fits (or in the middle of the first word when it alone is too long).
        stopwords: Words to leave out, whatever their case. A title that consists of
            stopwords only keeps its words.

    Returns:
        The slug; empty when ``text`` has no letters or digits that survive folding.

    Raises:
        TypeError: ``text`` is not a string.
        ValueError: ``separator`` or ``max_length`` is not allowed.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, not {type(text).__name__}")
    _check_options(separator, max_length)
    for symbol, word in SYMBOL_WORDS.items():
        text = text.replace(symbol, word)
    text = fold(text)
    for apostrophe in APOSTROPHES:
        text = text.replace(apostrophe, "")
    words = _WORD.findall(text.lower())
    skipped = {word.lower() for word in stopwords}
    kept = [word for word in words if word not in skipped]
    if kept:
        words = kept
    slug = separator.join(words)
    if max_length is not None:
        slug = _truncate(slug, separator, max_length)
    return slug
