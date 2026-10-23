"""Parser result types: ledger payloads before the recorder adds ``command_seq`` and ``source``.

Each type mirrors one payload TypedDict in :mod:`receipts.ledger.events` minus
the two fields only the recorder knows. :func:`to_test_run`, :func:`to_lint_run`
and :func:`to_typecheck_run` complete them.

Every :class:`ParsedTestRun` keeps ``total == passed + failed + errors + skipped``.
Expected failures (pytest ``xfailed``, unittest ``expected failures``) and to-do
tests count as skipped; unexpected passes that do not fail the run (pytest
``xpassed``) count as passed.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from receipts.ledger.events import (
    LintRunData,
    Source,
    TestCase,
    TestRunData,
    TypecheckRunData,
)


class ParsedTestRun(TypedDict):
    """A recognized test-suite summary (``test_run`` without ``command_seq`` and ``source``)."""

    framework: str
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int
    failing: list[str]
    collection_error: bool
    cases: NotRequired[list[TestCase]]


class ParsedLint(TypedDict):
    """A recognized linter summary (``lint_run`` without ``command_seq`` and ``source``)."""

    tool: str
    errors: int
    warnings: int


class ParsedTypecheck(TypedDict):
    """A recognized type-checker summary (``typecheck_run`` without the recorder fields)."""

    tool: str
    errors: int


def make_test_run(
    framework: str,
    *,
    passed: int,
    failed: int,
    errors: int,
    skipped: int,
    failing: list[str],
    collection_error: bool = False,
    cases: list[TestCase] | None = None,
) -> ParsedTestRun:
    """Build a :class:`ParsedTestRun`, computing ``total`` and adding ``cases`` when given."""
    run = ParsedTestRun(
        framework=framework,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        total=passed + failed + errors + skipped,
        failing=failing,
        collection_error=collection_error,
    )
    if cases:
        run["cases"] = cases
    return run


def to_test_run(parsed: ParsedTestRun, command_seq: int, source: Source) -> TestRunData:
    """Return the ``test_run`` payload for ``parsed``, derived from event ``command_seq``."""
    data = TestRunData(
        framework=parsed["framework"],
        command_seq=command_seq,
        passed=parsed["passed"],
        failed=parsed["failed"],
        errors=parsed["errors"],
        skipped=parsed["skipped"],
        total=parsed["total"],
        failing=list(parsed["failing"]),
        collection_error=parsed["collection_error"],
        source=source,
    )
    if "cases" in parsed:
        data["cases"] = [TestCase(name=c["name"], outcome=c["outcome"]) for c in parsed["cases"]]
    return data


def to_lint_run(parsed: ParsedLint, command_seq: int, source: Source) -> LintRunData:
    """Return the ``lint_run`` payload for ``parsed``, derived from event ``command_seq``."""
    return LintRunData(
        tool=parsed["tool"],
        command_seq=command_seq,
        errors=parsed["errors"],
        warnings=parsed["warnings"],
        source=source,
    )


def to_typecheck_run(parsed: ParsedTypecheck, command_seq: int, source: Source) -> TypecheckRunData:
    """Return the ``typecheck_run`` payload for ``parsed``, derived from event ``command_seq``."""
    return TypecheckRunData(
        tool=parsed["tool"], command_seq=command_seq, errors=parsed["errors"], source=source
    )
