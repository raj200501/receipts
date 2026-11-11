"""The headings of a Markdown page.

A heading is a line that starts with one to six ``#`` characters, after at most three
spaces of indentation, followed by a space, a tab, or the end of the line. A closing
run of ``#`` characters at the end of the line is not part of the text when a space
comes before it (``## Setup ##`` reads ``Setup``). Lines in fenced code blocks are
never headings. Underlined (setext) headings are not used in the handbook and are not
recognized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mdkit.blocks import scan
from mdkit.inline import plain_text

_ATX = re.compile(r"^ {0,3}(#{1,6})(?=[ \t]|$)(.*)$")
_CLOSING = re.compile(r"(?:^|[ \t])#+[ \t]*$")


@dataclass(frozen=True)
class Heading:
    """One heading of a page.

    Attributes:
        level: 1 for ``#`` up to 6 for ``######``.
        text: The heading text as written, with its inline Markdown.
        line: The 1-based line number.
    """

    level: int
    text: str
    line: int

    @property
    def title(self) -> str:
        """The heading text as the page shows it (without inline formatting)."""
        return plain_text(self.text)


def parse_heading(text: str, line: int) -> Heading | None:
    """The heading on one line outside fenced code, or None when it is not a heading."""
    match = _ATX.match(text)
    if match is None:
        return None
    marks, rest = match.groups()
    content = _CLOSING.sub("", rest.strip(" \t"))
    return Heading(level=len(marks), text=content.strip(" \t"), line=line)


def find_headings(text: str) -> list[Heading]:
    """Every heading of a page, in page order."""
    headings: list[Heading] = []
    for line in scan(text):
        if line.code:
            continue
        heading = parse_heading(line.text, line.number)
        if heading is not None:
            headings.append(heading)
    return headings


def outline(headings: list[Heading]) -> list[str]:
    """The lines ``mdkit outline`` prints: each title indented two spaces per level."""
    return [f"{'  ' * (heading.level - 1)}{heading.title}" for heading in headings]
