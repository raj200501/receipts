"""Inline Markdown: the text of a heading or a line as the page shows it.

:func:`plain_text` drops the inline formatting the handbook uses:

- code spans keep their content as it is (nothing inside them is formatting);
- links and images keep their text (``[text](target)`` reads ``text``);
- the markers of strong text, emphasis, and strikethrough are dropped
  (``**a**``, ``__a__``, ``*a*``, ``_a_``, ``~~a~~``); an underscore inside a word,
  as in ``snake_case``, is not a marker;
- a backslash escape stands for the character after it (``\\*`` reads ``*``).

HTML tags and autolinks are left as they are.
"""

from __future__ import annotations

import re

CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")

_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_PLACEHOLDER = re.compile("\ue000(\\d+)\ue001")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FORMATTING: tuple[re.Pattern[str], ...] = (
    re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"),
    re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"),
    re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"),
    re.compile(r"\*(?=\S)(.+?)(?<=\S)\*"),
    re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)"),
)


def _protect(match: re.Match[str]) -> str:
    return f"\ue000{ord(match.group(1))}\ue001"


def _restore(match: re.Match[str]) -> str:
    return chr(int(match.group(1)))


def _format(segment: str) -> str:
    """Plain text of a piece of inline Markdown that holds no code span."""
    text = _ESCAPE.sub(_protect, segment)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    for pattern in _FORMATTING:
        previous = None
        while previous != text:
            previous, text = text, pattern.sub(r"\1", text)
    return _PLACEHOLDER.sub(_restore, text)


def _code_content(raw: str) -> str:
    """A code span's content: one space is dropped at each end when both ends have one."""
    if len(raw) >= 2 and raw.startswith(" ") and raw.endswith(" ") and raw.strip():
        return raw[1:-1]
    return raw


def plain_text(text: str) -> str:
    """``text`` without inline Markdown formatting (see the module docstring)."""
    parts: list[str] = []
    position = 0
    for match in CODE_SPAN.finditer(text):
        parts.append(_format(text[position : match.start()]))
        parts.append(_code_content(match.group(2)))
        position = match.end()
    parts.append(_format(text[position:]))
    return "".join(parts).strip()
