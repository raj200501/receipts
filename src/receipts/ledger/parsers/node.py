"""Parsers for JavaScript test runners: ``node --test``, Jest, Vitest, and Mocha.

Each parser recognizes its runner by the final summary block, which the others
never print: TAP ``# tests N`` or spec ``\u2139 tests N`` lines (node), ``Tests:``
with a colon (Jest), ``Tests`` without one and ``|`` separators (Vitest), and
``N passing`` (Mocha). npm, pnpm and yarn wrappers add only header lines, which
the parsers ignore. Hierarchical test names are joined with ``" > "``.

Glyphs are written as escapes: \u2714 check, \u2716 cross, \u2139 info, \u25b6 arrow,
\ufe63 small hyphen (node spec); \u2713 check, \u2715 cross, \u25cb circle, \u270e pencil,
\u25cf bullet, \u203a angle quote (Jest); \u00d7 multiplication sign (Windows Jest).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from receipts.ledger.events import TestCase
from receipts.ledger.parsers.python_tests import merge_cases
from receipts.ledger.parsers.results import ParsedTestRun, make_test_run
from receipts.ledger.parsers.text import clean_lines

Outcome = Literal["passed", "failed", "error", "skipped"]
SEPARATOR = " > "

# node --test, TAP reporter
_TAP_SUMMARY = re.compile(
    r"^# (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) (\d+(?:\.\d+)?)$"
)
_TAP_TEST = re.compile(
    r"^(?P<indent> *)(?P<status>ok|not ok) (?P<number>\d+)(?: - (?P<name>.*?))?"
    r"(?: # (?P<directive>SKIP|TODO)\b.*)?$",
    re.IGNORECASE,
)
_TAP_SUBTEST = re.compile(r"^(?P<indent> *)# Subtest: (?P<name>.*)$")
_TAP_FAILURE_TYPE = re.compile(r"^\s+failureType: '(?P<type>\w+)'")

# node --test, spec reporter
_SPEC_SUMMARY = re.compile(
    "^\u2139 (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) (\\d+(?:\\.\\d+)?)$"
)
_SPEC_LINE = re.compile("^(?P<indent> *)(?P<glyph>[\u2714\u2716\ufe63\u25b6]) (?P<title>.+)$")
_SPEC_TITLE = re.compile(
    r"^(?P<name>.*?)(?: \((?P<ms>\d+(?:\.\d+)?)ms\))?(?: # (?P<directive>.*))?$"
)
_SPEC_FAILING_HEADER = "\u2716 failing tests:"

# Jest
_JEST_TESTS = re.compile(r"^Tests:\s+(?P<items>.*\d+ total)$")
_JEST_ITEM = re.compile(r"(\d+) (failed|passed|skipped|todo|pending)\b")
_JEST_FILE = re.compile(r"^\s*(?P<status>PASS|FAIL)\s+(?P<path>\S.*?)(?:\s+\([\d.]+ m?s\))?$")
_JEST_BULLET = re.compile("^\\s+\u25cf (?P<name>.+)$")
_JEST_CASE = re.compile(
    "^(?P<indent>\\s+)(?P<glyph>[\u2713\u2715\u25cb\u270e\u221a\u00d7]) (?P<title>.+?)"
    r"(?: \(\d+(?:\.\d+)? m?s\))?$"
)
_JEST_SUITE_FAILED = "Test suite failed to run"
_JEST_OUTCOMES: dict[str, Outcome] = {
    "\u2713": "passed",
    "\u221a": "passed",
    "\u2715": "failed",
    "\u00d7": "failed",
    "\u25cb": "skipped",
    "\u270e": "skipped",
}

# Vitest
_VITEST_TESTS = re.compile(r"^\s*Tests\s{2,}(?P<body>.+)$")
_VITEST_ITEM = re.compile(r"(\d+) (failed|passed|skipped|todo)\b")
_VITEST_ERRORS = re.compile(r"^\s*Errors\s{2,}(\d+) errors?\b")
_VITEST_FAIL = re.compile(r"^\s*FAIL\s+(?P<name>.+?)$")
_VITEST_SUITE = re.compile(r"^(?P<path>.+?) \[ .+ \]$")

# Mocha
_MOCHA_PASSING = re.compile(r"^\s*(\d+) passing(?: \(\S+\))?$")
_MOCHA_FAILING = re.compile(r"^\s*(\d+) failing$")
_MOCHA_PENDING = re.compile(r"^\s*(\d+) pending$")
_MOCHA_NUMBERED = re.compile(r"^(?P<indent>\s*)\d+\) (?P<title>.+)$")
_MOCHA_PASS = re.compile("^(?P<indent>\\s+)[\u2714\u2713] (?P<title>.+?)(?: \\(\\d+ms\\))?$")
_MOCHA_SKIP = re.compile(r"^(?P<indent>\s+)- (?P<title>.+)$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


class _Tree:
    """Tracks suite titles by indentation so nested tests get full names."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def close(self, indent: int) -> None:
        """Forget suites at ``indent`` or deeper."""
        while self._stack and self._stack[-1][0] >= indent:
            self._stack.pop()

    def open(self, indent: int, title: str) -> None:
        """Enter a suite titled ``title`` at ``indent``."""
        self.close(indent)
        self._stack.append((indent, title))

    def name(self, indent: int, title: str) -> str:
        """Full name of a test at ``indent``: enclosing suite titles plus ``title``."""
        self.close(indent)
        return SEPARATOR.join([t for _, t in self._stack] + [title])

    def ends_suite(self, indent: int, title: str) -> bool:
        """Whether ``title`` at ``indent`` is the result line of the suite open there.

        Node 22's spec reporter ends a suite (or a test with subtests) with a result
        line at the suite's own indentation: ``\u2714 title (ms)`` or ``\u2716 title
        (ms)``. When it does, the suite is forgotten and True is returned.
        """
        while self._stack and self._stack[-1][0] > indent:
            self._stack.pop()
        if self._stack and self._stack[-1] == (indent, title):
            self._stack.pop()
            return True
        return False


def _summary(lines: Sequence[str], pattern: re.Pattern[str]) -> dict[str, float] | None:
    """Add up ``key value`` summary lines (node TAP or spec); None without tests and pass."""
    totals: dict[str, float] = {}
    for line in lines:
        match = pattern.match(line)
        if match is not None:
            totals[match.group(1)] = totals.get(match.group(1), 0) + float(match.group(2))
    return totals if "tests" in totals and "pass" in totals else None


def _node_run(totals: dict[str, float], failing: list[str], cases: list[TestCase]) -> ParsedTestRun:
    return make_test_run(
        "node-test",
        passed=int(totals.get("pass", 0)),
        failed=int(totals.get("fail", 0)),
        errors=int(totals.get("cancelled", 0)),
        skipped=int(totals.get("skipped", 0) + totals.get("todo", 0)),
        failing=list(dict.fromkeys(failing)),
        cases=cases,
    )


def _parse_tap(lines: Sequence[str]) -> ParsedTestRun | None:
    totals = _summary(lines, _TAP_SUMMARY)
    if totals is None:
        return None
    subtests: dict[int, str] = {}
    open_indents: list[int] = []
    entries: list[tuple[str, Outcome]] = []
    for index, line in enumerate(lines):
        subtest = _TAP_SUBTEST.match(line)
        if subtest is not None:
            depth = len(subtest.group("indent"))
            subtests = {k: v for k, v in subtests.items() if k < depth}
            subtests[depth] = subtest.group("name")
            continue
        test = _TAP_TEST.match(line)
        if test is None:
            continue
        depth = len(test.group("indent"))
        is_parent = any(i > depth for i in open_indents)
        open_indents = [i for i in open_indents if i <= depth] + [depth]
        if is_parent:
            continue
        title = test.group("name") or subtests.get(depth) or f"test {test.group('number')}"
        name = SEPARATOR.join([subtests[k] for k in sorted(subtests) if k < depth] + [title])
        entries.append((name, _tap_outcome(test, lines, index)))
    failing = [name for name, outcome in entries if outcome in ("failed", "error")]
    return _node_run(totals, failing, merge_cases(entries))


def _tap_outcome(test: re.Match[str], lines: Sequence[str], index: int) -> Outcome:
    """Outcome of one TAP test line, reading its YAML block for the failure type."""
    if test.group("directive"):
        return "skipped"
    if test.group("status").lower() == "ok":
        return "passed"
    for line in lines[index + 1 :]:
        if _TAP_TEST.match(line) or _TAP_SUBTEST.match(line):
            break
        failure = _TAP_FAILURE_TYPE.match(line)
        if failure is not None:
            return "error" if failure.group("type") == "cancelledByParent" else "failed"
    return "failed"


def _parse_spec(lines: Sequence[str]) -> ParsedTestRun | None:
    totals = _summary(lines, _SPEC_SUMMARY)
    if totals is None:
        return None
    cut = lines.index(_SPEC_FAILING_HEADER) if _SPEC_FAILING_HEADER in lines else len(lines)
    tree = _Tree()
    entries: list[tuple[str, Outcome]] = []
    for line in lines[:cut]:
        match = _SPEC_LINE.match(line)
        if match is None:
            continue
        depth = len(match.group("indent"))
        title = _SPEC_TITLE.match(match.group("title"))
        assert title is not None  # the pattern accepts any text
        name, glyph = title.group("name"), match.group("glyph")
        if glyph == "\u25b6":
            if title.group("ms") is None:
                tree.open(depth, name)
            else:
                tree.close(depth)
            continue
        if title.group("ms") is not None and tree.ends_suite(depth, name):
            continue
        outcome: Outcome
        if glyph == "\ufe63" or title.group("directive") is not None:
            outcome = "skipped"
        else:
            outcome = "passed" if glyph == "\u2714" else "failed"
        entries.append((tree.name(depth, name), outcome))
    failing = [name for name, outcome in entries if outcome == "failed"]
    if not failing:
        for line in lines[cut + 1 :]:
            match = _SPEC_LINE.match(line)
            if match is not None and match.group("glyph") == "\u2716" and not line[0].isspace():
                title = _SPEC_TITLE.match(match.group("title"))
                assert title is not None
                failing.append(title.group("name"))
    return _node_run(totals, failing, merge_cases(entries))


def parse_node_test(text: str) -> ParsedTestRun | None:
    """Parse ``node --test`` output from the TAP or the spec reporter.

    Counts come from the summary (``# tests``/``\u2139 tests`` and siblings): pass,
    fail, cancelled (counted as errors), skipped plus todo (counted as skipped).
    ``failing`` and ``cases`` cover leaf tests only; a suite or parent test that
    failed because a child failed is not listed. Returns None without a summary.
    """
    lines = clean_lines(text)
    return _parse_tap(lines) or _parse_spec(lines)


def parse_jest(text: str) -> ParsedTestRun | None:
    """Parse Jest output, recognized by its ``Tests:  ... N total`` line.

    A test file that fails to load ("Test suite failed to run") counts as one
    error and its path is listed in ``failing``; when no test ran at all,
    ``collection_error`` is set. Names from ``\u25cf`` failure headers and from
    ``--verbose`` trees use ``" > "`` between describe blocks and the test.
    """
    lines = clean_lines(text)
    counts: dict[str, int] = {}
    found = False
    for line in lines:
        match = _JEST_TESTS.match(line)
        if match is not None:
            found = True
            for value, word in _JEST_ITEM.findall(match.group("items")):
                counts[word] = counts.get(word, 0) + int(value)
    if not found:
        return None

    failing: list[str] = []
    entries: list[tuple[str, Outcome]] = []
    suite_errors = 0
    current_file = ""
    tree = _Tree()
    in_tree = False
    for line in lines:
        file_line = _JEST_FILE.match(line)
        if file_line is not None:
            current_file, in_tree, tree = file_line.group("path"), True, _Tree()
            continue
        bullet = _JEST_BULLET.match(line)
        if bullet is not None:
            in_tree = False
            name = bullet.group("name")
            if name == _JEST_SUITE_FAILED:
                suite_errors += 1
                failing.append(current_file)
            elif not name.endswith(":"):
                failing.append(name.replace(" \u203a ", SEPARATOR))
            continue
        if not in_tree or not line.strip():
            in_tree = in_tree and bool(line.strip())
            continue
        case = _JEST_CASE.match(line)
        if case is None:
            tree.open(_indent(line), line.strip())
            continue
        title = case.group("title")
        for prefix in ("skipped ", "todo "):
            title = title.removeprefix(prefix)
        entries.append((tree.name(_indent(line), title), _JEST_OUTCOMES[case.group("glyph")]))

    passed, failed = counts.get("passed", 0), counts.get("failed", 0)
    skipped = counts.get("skipped", 0) + counts.get("todo", 0) + counts.get("pending", 0)
    return make_test_run(
        "jest",
        passed=passed,
        failed=failed,
        errors=suite_errors,
        skipped=skipped,
        failing=list(dict.fromkeys(failing)),
        collection_error=suite_errors > 0 and passed + failed + skipped == 0,
        cases=merge_cases(entries),
    )


def parse_vitest(text: str) -> ParsedTestRun | None:
    """Parse Vitest output, recognized by its ``Tests  1 failed | 4 passed (5)`` line.

    A test file that fails to load (a ``FAIL  path [ path ]`` entry) and each
    unhandled error (``Errors  N errors``) count as errors; when files failed to
    load and no test ran (``Tests  no tests``), ``collection_error`` is set.
    ``failing`` holds the ``FAIL`` names as printed (``file > suite > test``).
    """
    lines = clean_lines(text)
    counts: dict[str, int] = {}
    found = False
    unhandled = 0
    for line in lines:
        match = _VITEST_TESTS.match(line)
        if match is not None:
            body = match.group("body").strip()
            if body != "no tests" and not re.search(r"\(\d+\)$", body):
                continue
            found = True
            for value, word in _VITEST_ITEM.findall(body):
                counts[word] = counts.get(word, 0) + int(value)
            continue
        errors_line = _VITEST_ERRORS.match(line)
        if errors_line is not None:
            unhandled += int(errors_line.group(1))
    if not found:
        return None

    failing: list[str] = []
    broken_files: list[str] = []
    for line in lines:
        fail = _VITEST_FAIL.match(line)
        if fail is None:
            continue
        suite = _VITEST_SUITE.match(fail.group("name"))
        if suite is not None:
            broken_files.append(suite.group("path"))
        failing.append(suite.group("path") if suite else fail.group("name"))
    broken = len(dict.fromkeys(broken_files))
    passed, failed = counts.get("passed", 0), counts.get("failed", 0)
    skipped = counts.get("skipped", 0) + counts.get("todo", 0)
    return make_test_run(
        "vitest",
        passed=passed,
        failed=failed,
        errors=broken + unhandled,
        skipped=skipped,
        failing=list(dict.fromkeys(failing)),
        collection_error=broken > 0 and passed + failed + skipped == 0,
    )


def _mocha_failure_names(lines: Sequence[str]) -> list[str]:
    """Full titles from Mocha's numbered failure details (one title part per line)."""
    names: list[str] = []
    index = 0
    while index < len(lines):
        match = _MOCHA_NUMBERED.match(lines[index])
        index += 1
        if match is None:
            continue
        parts = [match.group("title")]
        while not parts[-1].endswith(":") and index < len(lines) and lines[index].strip():
            parts.append(lines[index].strip())
            index += 1
        parts[-1] = parts[-1].removesuffix(":")
        names.append(SEPARATOR.join(parts))
    return names


def parse_mocha(text: str) -> ParsedTestRun | None:
    """Parse Mocha spec-reporter output, recognized by its ``N passing (12ms)`` line.

    ``N pending`` counts as skipped. Failing hooks count as failures, as Mocha
    counts them. ``failing`` comes from the numbered details after ``N failing``
    (falling back to numbered lines in the test tree), with suite titles joined
    by ``" > "``.
    """
    lines = clean_lines(text)
    first = next((i for i, line in enumerate(lines) if _MOCHA_PASSING.match(line)), None)
    if first is None:
        return None
    counts = {"passing": 0, "failing": 0, "pending": 0}
    details_start = len(lines)
    for index, line in enumerate(lines):
        for key, pattern in (
            ("passing", _MOCHA_PASSING),
            ("failing", _MOCHA_FAILING),
            ("pending", _MOCHA_PENDING),
        ):
            match = pattern.match(line)
            if match is not None:
                counts[key] += int(match.group(1))
                if key == "failing":
                    details_start = min(details_start, index + 1)

    tree = _Tree()
    entries: list[tuple[str, Outcome]] = []
    for line in lines[:first]:
        if not line.strip() or not line[0].isspace():
            continue
        depth = _indent(line)
        passed_case = _MOCHA_PASS.match(line)
        failed_case = _MOCHA_NUMBERED.match(line)
        skipped_case = _MOCHA_SKIP.match(line)
        if passed_case is not None:
            entries.append((tree.name(depth, passed_case.group("title")), "passed"))
        elif failed_case is not None:
            entries.append((tree.name(depth, failed_case.group("title")), "failed"))
        elif skipped_case is not None:
            entries.append((tree.name(depth, skipped_case.group("title")), "skipped"))
        else:
            tree.open(depth, line.strip())
    failing = _mocha_failure_names(lines[details_start:]) or [
        name for name, outcome in entries if outcome == "failed"
    ]
    return make_test_run(
        "mocha",
        passed=counts["passing"],
        failed=counts["failing"],
        errors=0,
        skipped=counts["pending"],
        failing=list(dict.fromkeys(failing)),
        cases=merge_cases(entries),
    )
