"""Text clean-up shared by every parser: ANSI escapes, carriage returns, line splitting."""

from __future__ import annotations

import re

# CSI sequences (colors, cursor moves), OSC sequences (titles, hyperlinks),
# character-set designations (``tput sgr0`` emits ESC ( B), and two-character
# escapes, in that order of preference.
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()*+][0-9A-Za-z]|\x1b[@-_]"
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (colors, cursor movement, hyperlinks) from ``text``."""
    return _ANSI_RE.sub("", text)


def clean_lines(text: str) -> list[str]:
    """Split terminal output into lines with escapes removed and overwrites resolved.

    ANSI sequences are stripped, ``\\r\\n`` counts as one line break, a lone ``\\r``
    (a progress line rewritten in place) keeps only the last non-blank rewrite,
    and trailing whitespace is removed from every line.
    """
    lines: list[str] = []
    for raw in strip_ansi(text).replace("\r\n", "\n").split("\n"):
        line = raw
        if "\r" in line:
            parts = [part for part in line.split("\r") if part.strip()]
            line = parts[-1] if parts else ""
        lines.append(line.rstrip())
    return lines
