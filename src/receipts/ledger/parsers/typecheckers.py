"""Parsers for type checkers: mypy, pyright (and basedpyright), and tsc.

Each returns None when its tool's output is not present. Several summaries of
the same tool in one output are added.
"""

from __future__ import annotations

import re

from receipts.ledger.parsers.results import ParsedTypecheck
from receipts.ledger.parsers.text import clean_lines

_MYPY_SUCCESS = re.compile(r"^Success: no issues found in \d+ source files?$")
_MYPY_FOUND = re.compile(
    r"^Found (\d+) errors? in \d+ files? \((?:checked \d+ source files?|errors prevented .*)\)$"
)
_MYPY_ERROR_LINE = re.compile(r"^[^\s:][^:]*:\d+(?::\d+)?: error: .*\[[a-z0-9-]+\]$")
_PYRIGHT_SUMMARY = re.compile(
    r"^(\d+) errors?, (\d+) warnings?, (\d+) (?:informations?|infos?|notes?)$"
)
_TSC_ERROR = re.compile(r"(?:^|[\s:)])error TS\d+:")
_TSC_SUMMARY = re.compile(
    r"^(?:\[[^\]]+\] |\S+ (?:AM|PM) - )?Found (\d+) errors?"
    r"(?:\.(?: Watching for file changes\.)?"
    r"| in the same file, starting at: .+| in \d+ files\.| in \S+:\d+)$"
)


def parse_mypy(text: str) -> ParsedTypecheck | None:
    """Parse mypy output: ``Success: no issues found ...`` or ``Found N errors in M files ...``.

    Without a summary (``--no-error-summary``), ``path:line: error: ... [code]``
    lines are counted instead. Returns None when neither is present.
    """
    found = False
    errors = 0
    error_lines = 0
    for line in clean_lines(text):
        if _MYPY_SUCCESS.match(line):
            found = True
            continue
        match = _MYPY_FOUND.match(line)
        if match is not None:
            found = True
            errors += int(match.group(1))
        elif _MYPY_ERROR_LINE.match(line):
            error_lines += 1
    if found:
        return ParsedTypecheck(tool="mypy", errors=errors)
    if error_lines:
        return ParsedTypecheck(tool="mypy", errors=error_lines)
    return None


def parse_pyright(text: str) -> ParsedTypecheck | None:
    """Parse pyright's ``N errors, M warnings, K informations`` summary line."""
    found = False
    errors = 0
    for line in clean_lines(text):
        match = _PYRIGHT_SUMMARY.match(line.strip())
        if match is not None:
            found = True
            errors += int(match.group(1))
    return ParsedTypecheck(tool="pyright", errors=errors) if found else None


def parse_tsc(text: str) -> ParsedTypecheck | None:
    """Parse tsc output: ``error TS1234:`` lines and the optional ``Found N errors`` summary.

    The summary count is used when present, else the error lines are counted.
    tsc prints nothing on success outside watch mode, so a clean run is
    recognized only from the command, or from ``Found 0 errors. Watching for
    file changes.``. Returns None when there are no error lines and no summary
    after an error line or a watch-mode line.
    """
    lines = clean_lines(text)
    error_lines = sum(1 for line in lines if _TSC_ERROR.search(line))
    summaries = [m for line in lines if (m := _TSC_SUMMARY.match(line.strip()))]
    watching = any("Watching for file changes" in m.group(0) for m in summaries)
    if error_lines == 0 and not watching:
        return None
    if summaries:
        return ParsedTypecheck(tool="tsc", errors=sum(int(m.group(1)) for m in summaries))
    return ParsedTypecheck(tool="tsc", errors=error_lines)
