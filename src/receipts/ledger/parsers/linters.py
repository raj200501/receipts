"""Parsers for linters and formatter checks: ruff, flake8, ESLint, ``ruff format --check``, black.

Each returns None when its tool's output is not present. Several summaries of
the same tool in one output (a wrapper that lints two directories) are added.
"""

from __future__ import annotations

import re

from receipts.ledger.parsers.results import ParsedLint
from receipts.ledger.parsers.text import clean_lines

_RUFF_CLEAN = "All checks passed!"
_RUFF_FOUND = re.compile(r"^Found (\d+) errors?(?: \((\d+) fixed, (\d+) remaining\))?\.$")
_FLAKE8_LINE = re.compile(r"^(?P<path>[^\s:][^:]*):\d+:\d+: (?P<code>[A-Z]{1,3}\d{1,4}) \S")
_ESLINT_SUMMARY = re.compile(
    "^[\u2716\u00d7] (\\d+) problems? \\((\\d+) errors?, (\\d+) warnings?\\)$"
)
_WOULD_REFORMAT = re.compile(r"^(\d+) files? would be reformatted\b")
_ALREADY_FORMATTED = re.compile(
    r"^(?:\d+ files? would be reformatted, )?\d+ files? "
    r"(?:already formatted|would be left unchanged)\.?$"
)
_BLACK_MARKERS = ("would be left unchanged", "Oh no!", "All done!")


def parse_ruff(text: str) -> ParsedLint | None:
    """Parse ``ruff check`` output: ``All checks passed!`` or ``Found N errors.``.

    With ``--fix``, the summary ``Found 3 errors (2 fixed, 1 remaining).`` counts
    only the remaining errors. ruff reports no warnings, so ``warnings`` is 0.
    A bare ``Found N errors.`` line is also what older tsc versions print;
    :func:`receipts.ledger.parsers.detect.analyze_output` resolves that case.
    """
    found = False
    errors = 0
    for line in clean_lines(text):
        stripped = line.strip()
        if stripped == _RUFF_CLEAN:
            found = True
            continue
        match = _RUFF_FOUND.match(stripped)
        if match is not None:
            found = True
            errors += int(match.group(3) if match.group(3) is not None else match.group(1))
    return ParsedLint(tool="ruff", errors=errors, warnings=0) if found else None


def parse_flake8(text: str) -> ParsedLint | None:
    """Parse flake8's ``path:line:col: CODE message`` lines.

    Codes starting with ``W`` (pycodestyle warnings) count as warnings and every
    other code as an error. Returns None when no such line is present; flake8
    prints nothing on success, so a clean run is recognized only from the
    command (see :func:`receipts.ledger.parsers.detect.analyze_output`).
    """
    errors = warnings = 0
    for line in clean_lines(text):
        match = _FLAKE8_LINE.match(line)
        if match is None:
            continue
        if match.group("code").startswith("W"):
            warnings += 1
        else:
            errors += 1
    if errors + warnings == 0:
        return None
    return ParsedLint(tool="flake8", errors=errors, warnings=warnings)


def parse_eslint(text: str) -> ParsedLint | None:
    """Parse ESLint's ``\u2716 N problems (E errors, W warnings)`` summary (stylish formatter).

    ESLint prints nothing when there are no problems, so a clean run is
    recognized only from the command.
    """
    found = False
    errors = warnings = 0
    for line in clean_lines(text):
        match = _ESLINT_SUMMARY.match(line.strip())
        if match is not None:
            found = True
            errors += int(match.group(2))
            warnings += int(match.group(3))
    return ParsedLint(tool="eslint", errors=errors, warnings=warnings) if found else None


def parse_format_check(text: str) -> ParsedLint | None:
    """Parse a formatter check (``ruff format --check`` or ``black --check``).

    Each file that would be reformatted counts as one error. The tool is
    ``"black"`` when black's wording is present and ``"ruff-format"`` otherwise.
    A formatter run without ``--check`` (``1 file reformatted``) is not a check
    and is not recognized.
    """
    lines = [line.strip() for line in clean_lines(text)]
    found = False
    errors = 0
    for line in lines:
        would = _WOULD_REFORMAT.match(line)
        if would is not None:
            found = True
            errors += int(would.group(1))
        elif _ALREADY_FORMATTED.match(line):
            found = True
    if not found:
        return None
    tool = "black" if any(m in line for line in lines for m in _BLACK_MARKERS) else "ruff-format"
    return ParsedLint(tool=tool, errors=errors, warnings=0)
