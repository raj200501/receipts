"""Split a Markdown page into lines and mark the lines of fenced code blocks.

A fenced code block starts with a line of at least three backticks or three tildes,
indented by at most three spaces. A backtick fence may be followed by an info string
(``python``), which may not contain backticks. The block ends with a line of the same
fence character, at least as long as the opening fence, with nothing after it but
spaces. A block that is never closed runs to the end of the page. The fence lines
belong to the block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TEXT = "text"
OPEN = "open"
CODE = "code"
CLOSE = "close"

_OPENING = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CLOSING = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


@dataclass(frozen=True)
class Line:
    """One line of a page.

    Attributes:
        number: The 1-based line number.
        text: The line without its line ending.
        kind: ``text`` for ordinary lines; for fenced code ``open`` (the opening
            fence), ``code`` (a line inside the block), or ``close`` (the closing fence).
    """

    number: int
    text: str
    kind: str = TEXT

    @property
    def code(self) -> bool:
        """True for every line of a fenced code block, the fences included."""
        return self.kind != TEXT


def _opening_fence(text: str) -> str | None:
    """The fence that ``text`` opens, or None when it is not an opening fence."""
    match = _OPENING.match(text)
    if match is None:
        return None
    fence, info = match.groups()
    if fence.startswith("`") and "`" in info:
        return None
    return fence


def _closes(text: str, fence: str) -> bool:
    match = _CLOSING.match(text)
    if match is None:
        return False
    closing = match.group(1)
    return closing[0] == fence[0] and len(closing) >= len(fence)


def scan(text: str) -> list[Line]:
    """Every line of ``text`` with its kind, in order."""
    lines: list[Line] = []
    fence = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        if fence:
            if _closes(raw, fence):
                lines.append(Line(number, raw, CLOSE))
                fence = ""
            else:
                lines.append(Line(number, raw, CODE))
            continue
        opened = _opening_fence(raw)
        if opened is not None:
            fence = opened
            lines.append(Line(number, raw, OPEN))
        else:
            lines.append(Line(number, raw, TEXT))
    return lines


def count_code_blocks(text: str) -> int:
    """How many fenced code blocks ``text`` has (an unclosed block counts)."""
    return sum(1 for line in scan(text) if line.kind == OPEN)
