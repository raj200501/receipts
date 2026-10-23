"""Parsers for Python test runners: pytest terminal output and ``python -m unittest``.

pytest is recognized by its final summary line, bordered (``=== 2 failed, 10 passed
in 0.12s ===``) or bare as in ``-q`` mode (``2 failed, 10 passed in 0.12s``). Output
with no summary line (a run cut off or killed) is not recognized, because partial
progress lines do not say how the run ended. When one output holds several
sessions (a wrapper that runs pytest twice), their counts are added.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Literal

from receipts.ledger.events import TestCase
from receipts.ledger.parsers.results import ParsedTestRun, make_test_run
from receipts.ledger.parsers.text import clean_lines

Outcome = Literal["passed", "failed", "error", "skipped"]

_COUNT_WORDS = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "deselected": "deselected",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
    "warning": "warnings",
    "warnings": "warnings",
    "error": "errors",
    "errors": "errors",
    "rerun": "reruns",
    "reruns": "reruns",
}
_BORDERED = re.compile(r"^=+ (?P<inner>.+?) =+$")
_TIMED = re.compile(r"^(?P<counts>.+?) in \d+(?:\.\d+)?\s?s(?:econds)?(?: \([0-9:.]+\))?$")
_COUNT_ITEM = re.compile(r"^(\d+) ([a-z]+)$")
_INTERRUPTED = re.compile(r"Interrupted: \d+ errors? during collection")
_COLLECT_HEADER = re.compile(r"^_+ ERROR collecting (?P<path>.+?) _+$")
_SECTION = re.compile(r"^=+ (?P<name>[A-Za-z][A-Za-z ]*?) =+$")
_SHORT_HEADER = "short test summary info"
_SHORT_LINE = re.compile(r"^(?P<outcome>FAILED|ERROR|PASSED|XFAIL|XPASS) (?P<rest>\S.*)$")
_VERBOSE_LINE = re.compile(
    r"^(?P<id>\S+::.+?) (?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)"
    r"(?: \(.*\))?(?:\s+\[\s*\d+%\])?$"
)
_XDIST_LINE = re.compile(
    r"^\[gw\d+\] \[\s*\d+%\] (?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (?P<id>\S+::.+)$"
)
_FAILURE_HEADER = re.compile(r"^_{3,} (?P<title>.+?) _{3,}$")
_HEADER_PREFIXES = ("ERROR at setup of ", "ERROR at teardown of ", "ERROR collecting ")

_PYTEST_OUTCOMES: dict[str, Outcome] = {
    "PASSED": "passed",
    "FAILED": "failed",
    "ERROR": "error",
    "SKIPPED": "skipped",
    "XFAIL": "skipped",
    "XPASS": "passed",
}
_SEVERITY: dict[str, int] = {"skipped": 0, "passed": 1, "failed": 2, "error": 3}


def _summary_counts(line: str) -> dict[str, int] | None:
    """Return the counts on a pytest final summary line, or None if it is not one."""
    if not line or line[0].isspace():
        return None
    bordered = _BORDERED.match(line)
    timed = _TIMED.match(bordered.group("inner") if bordered else line)
    if timed is None:
        return None
    counts: dict[str, int] = {}
    for part in timed.group("counts").split(", "):
        if part == "no tests ran":
            continue
        item = _COUNT_ITEM.match(part)
        if item is None or item.group(2) not in _COUNT_WORDS:
            return None
        key = _COUNT_WORDS[item.group(2)]
        counts[key] = counts.get(key, 0) + int(item.group(1))
    return counts


def split_nodeid(rest: str) -> str:
    """Return the pytest node ID at the start of ``rest``.

    The ID ends at the first space outside square brackets, so parametrized IDs
    such as ``test_parse[a - b]`` survive intact.
    """
    depth = 0
    for index, char in enumerate(rest):
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        elif char == " " and depth == 0:
            return rest[:index]
    return rest


def _short_summary(lines: Sequence[str]) -> list[tuple[str, str]]:
    """``(OUTCOME, nodeid)`` pairs from "short test summary info" sections."""
    has_header = any(line.startswith("=") and _SHORT_HEADER in line for line in lines)
    entries: list[tuple[str, str]] = []
    in_region = False
    for line in lines:
        if line.startswith("=") and _SHORT_HEADER in line:
            in_region = True
            continue
        if has_header:
            if not in_region:
                continue
            if line.startswith(("=", "!")):
                in_region = False
                continue
        match = _SHORT_LINE.match(line)
        if match is None:
            continue
        nodeid = split_nodeid(match.group("rest"))
        if has_header or "::" in nodeid or nodeid.endswith(".py"):
            entries.append((match.group("outcome"), nodeid))
    return entries


def _verbose_entries(lines: Iterable[str]) -> list[tuple[str, str]]:
    """``(OUTCOME, nodeid)`` pairs from ``-v`` progress lines, including pytest-xdist's form."""
    entries: list[tuple[str, str]] = []
    for line in lines:
        match = _VERBOSE_LINE.match(line) or _XDIST_LINE.match(line)
        if match is not None:
            entries.append((match.group("outcome"), match.group("id")))
    return entries


def _failure_titles(lines: Iterable[str]) -> list[str]:
    """Test titles from the headers in the FAILURES and ERRORS sections."""
    section = ""
    titles: list[str] = []
    for line in lines:
        header = _SECTION.match(line)
        if header is not None:
            section = header.group("name")
            continue
        if section not in ("FAILURES", "ERRORS"):
            continue
        match = _FAILURE_HEADER.match(line)
        if match is None:
            continue
        title = match.group("title")
        for prefix in _HEADER_PREFIXES:
            if title.startswith(prefix):
                title = title[len(prefix) :]
        titles.append(title)
    return titles


def _dedupe(names: Iterable[str]) -> list[str]:
    """Drop repeated names, keeping first-seen order."""
    return list(dict.fromkeys(names))


def merge_cases(entries: Iterable[tuple[str, Outcome]]) -> list[TestCase]:
    """One case per name, keeping the most severe outcome seen and first-seen order."""
    merged: dict[str, Outcome] = {}
    for name, outcome in entries:
        known = merged.get(name)
        if known is None or _SEVERITY[outcome] > _SEVERITY[known]:
            merged[name] = outcome
    return [TestCase(name=name, outcome=outcome) for name, outcome in merged.items()]


def parse_pytest(text: str) -> ParsedTestRun | None:
    """Parse pytest terminal output (normal, ``-q``, ``-v`` and ``-rA`` modes).

    Returns None when no final summary line is present. ``failing`` lists the
    node IDs of failed and errored tests, from the short test summary when
    present, else from ``-v`` lines, collection-error headers, and finally the
    FAILURES and ERRORS section headers. ``cases`` lists every test whose
    outcome the output names, when any does. ``collection_error`` is set when
    pytest stopped during collection, or when collection failed and no test ran.
    """
    lines = clean_lines(text)
    found = False
    totals: dict[str, int] = {}
    for line in lines:
        counts = _summary_counts(line)
        if counts is not None:
            found = True
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
    if not found:
        return None

    passed = totals.get("passed", 0) + totals.get("xpassed", 0)
    failed = totals.get("failed", 0)
    errors = totals.get("errors", 0)
    skipped = totals.get("skipped", 0) + totals.get("xfailed", 0)
    collect_paths = [m.group("path") for line in lines if (m := _COLLECT_HEADER.match(line))]
    interrupted = any(_INTERRUPTED.search(line) for line in lines)
    collection_error = interrupted or (bool(collect_paths) and passed + failed + skipped == 0)

    short = _short_summary(lines)
    verbose = _verbose_entries(lines)
    bad = ("FAILED", "ERROR")
    failing = _dedupe(
        [nodeid for outcome, nodeid in short if outcome in bad]
        + [nodeid for outcome, nodeid in verbose if outcome in bad]
        + collect_paths
    )
    if not failing and failed + errors > 0:
        failing = _dedupe(_failure_titles(lines))
    cases = merge_cases((nodeid, _PYTEST_OUTCOMES[outcome]) for outcome, nodeid in verbose + short)
    return make_test_run(
        "pytest",
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        failing=failing,
        collection_error=collection_error,
        cases=cases,
    )


_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in \d+(?:\.\d+)?s$")
_UNITTEST_RESULT = re.compile(r"^(?:OK|FAILED|NO TESTS RAN)(?: \((?P<details>[^)]*)\))?$")
_UNITTEST_DETAIL = re.compile(r"^([a-z ]+)=(\d+)$")
_UNITTEST_HEADER = re.compile(
    r"^(?P<kind>FAIL|ERROR|UNEXPECTED SUCCESS): (?P<name>\S+) \((?P<where>[^)]*)\)"
)
_UNITTEST_CASE = re.compile(
    r"^(?P<name>\S+) \((?P<where>[^)]*)\) \.\.\. "
    r"(?P<result>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)$"
)
_UNITTEST_OUTCOMES: dict[str, Outcome] = {
    "ok": "passed",
    "FAIL": "failed",
    "ERROR": "error",
    "expected failure": "skipped",
    "unexpected success": "failed",
}


def _unittest_name(name: str, where: str) -> str:
    """Full dotted test ID from unittest's ``name (where)`` form (old and 3.11+ styles)."""
    if "_FailedTest" in where:
        return name
    if where == name or where.endswith("." + name):
        return where
    return f"{where}.{name}"


def parse_unittest(text: str) -> ParsedTestRun | None:
    """Parse ``python -m unittest`` output, recognized by its ``Ran N tests in`` line.

    Unexpected successes count as failures and expected failures as skipped. A
    module that fails to import (``unittest.loader._FailedTest``) counts as an
    error; when every test is such a failure, ``collection_error`` is set.
    """
    lines = clean_lines(text)
    found = False
    ran = 0
    details: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = _UNITTEST_RAN.match(line)
        if match is None:
            continue
        following = [rest for rest in lines[index + 1 :] if rest.strip()]
        result = _UNITTEST_RESULT.match(following[0]) if following else None
        if result is None:
            continue
        found = True
        ran += int(match.group(1))
        for part in (result.group("details") or "").split(", "):
            detail = _UNITTEST_DETAIL.match(part.strip())
            if detail is not None:
                details[detail.group(1)] = details.get(detail.group(1), 0) + int(detail.group(2))
    if not found:
        return None

    failed = details.get("failures", 0) + details.get("unexpected successes", 0)
    errors = details.get("errors", 0)
    skipped = details.get("skipped", 0) + details.get("expected failures", 0)
    passed = max(ran - failed - errors - skipped, 0)
    headers = [m for line in lines if (m := _UNITTEST_HEADER.match(line))]
    failing = _dedupe(_unittest_name(m.group("name"), m.group("where")) for m in headers)
    load_failures = sum(1 for m in headers if "_FailedTest" in m.group("where"))
    entries: list[tuple[str, Outcome]] = []
    for line in lines:
        case = _UNITTEST_CASE.match(line)
        if case is not None:
            word = case.group("result")
            outcome: Outcome = "skipped" if word.startswith("skipped") else _UNITTEST_OUTCOMES[word]
            entries.append((_unittest_name(case.group("name"), case.group("where")), outcome))
    return make_test_run(
        "unittest",
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        failing=failing,
        collection_error=load_failures > 0 and load_failures >= ran,
        cases=merge_cases(entries),
    )
