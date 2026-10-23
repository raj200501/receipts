"""Tests for the linter and type-checker parsers (hand-written fixtures)."""

from __future__ import annotations

import pytest

from receipts.ledger.parsers.linters import (
    parse_eslint,
    parse_flake8,
    parse_format_check,
    parse_ruff,
)
from receipts.ledger.parsers.typecheckers import parse_mypy, parse_pyright, parse_tsc

from .helpers import fixture


@pytest.mark.parametrize(
    ("name", "errors"),
    [
        ("lint/ruff_full.txt", 3),
        ("lint/ruff_concise.txt", 2),
        ("lint/ruff_clean.txt", 0),
        ("lint/ruff_fixed.txt", 1),
        ("mixed/make_lint_fail.txt", 1),
    ],
)
def test_ruff(name: str, errors: int) -> None:
    assert parse_ruff(fixture(name)) == {"tool": "ruff", "errors": errors, "warnings": 0}


def test_ruff_sums_runs_and_ignores_other_output() -> None:
    assert parse_ruff("Found 2 errors.\nAll checks passed!\nFound 1 error.\n") == {
        "tool": "ruff",
        "errors": 3,
        "warnings": 0,
    }
    assert parse_ruff("") is None
    assert parse_ruff("Found 2 errors in 1 file (checked 3 source files)\n") is None


def test_flake8_splits_errors_and_warnings() -> None:
    assert parse_flake8(fixture("lint/flake8.txt")) == {
        "tool": "flake8",
        "errors": 2,
        "warnings": 1,
    }
    assert parse_flake8("") is None
    assert parse_flake8("src/a.py:3: error: mypy style  [misc]\n") is None


@pytest.mark.parametrize(
    ("name", "errors", "warnings"),
    [("lint/eslint_npm.txt", 2, 1), ("lint/eslint_ansi.txt", 1, 0)],
)
def test_eslint(name: str, errors: int, warnings: int) -> None:
    assert parse_eslint(fixture(name)) == {"tool": "eslint", "errors": errors, "warnings": warnings}


def test_eslint_silent_success_is_not_recognized_from_output_alone() -> None:
    assert parse_eslint(fixture("lint/eslint_clean_npm.txt")) is None


def test_format_checks() -> None:
    assert parse_format_check(fixture("lint/ruff_format_check.txt")) == {
        "tool": "ruff-format",
        "errors": 2,
        "warnings": 0,
    }
    assert parse_format_check(fixture("lint/black_check.txt")) == {
        "tool": "black",
        "errors": 1,
        "warnings": 0,
    }
    assert parse_format_check("9 files already formatted\n") == {
        "tool": "ruff-format",
        "errors": 0,
        "warnings": 0,
    }
    assert parse_format_check("All done!\n3 files would be left unchanged.\n") == {
        "tool": "black",
        "errors": 0,
        "warnings": 0,
    }
    assert parse_format_check("1 file reformatted, 8 files left unchanged\n") is None


@pytest.mark.parametrize(
    ("name", "errors"),
    [
        ("typecheck/mypy_errors.txt", 2),
        ("typecheck/mypy_clean.txt", 0),
        ("typecheck/mypy_no_summary.txt", 2),
    ],
)
def test_mypy(name: str, errors: int) -> None:
    assert parse_mypy(fixture(name)) == {"tool": "mypy", "errors": errors}


def test_mypy_variants_and_not_recognized() -> None:
    text = "Found 1 error in 1 file (errors prevented further checking)\n"
    assert parse_mypy(text) == {"tool": "mypy", "errors": 1}
    assert parse_mypy("Found 2 errors.\n") is None
    assert parse_mypy("") is None


@pytest.mark.parametrize(
    ("name", "errors"),
    [("typecheck/pyright_errors.txt", 1), ("typecheck/pyright_clean.txt", 0)],
)
def test_pyright(name: str, errors: int) -> None:
    assert parse_pyright(fixture(name)) == {"tool": "pyright", "errors": errors}


def test_pyright_variants() -> None:
    assert parse_pyright("2 errors, 0 warnings, 0 notes\n") == {"tool": "pyright", "errors": 2}
    assert parse_pyright("") is None


@pytest.mark.parametrize(
    ("name", "errors"),
    [
        ("typecheck/tsc_plain_npm.txt", 2),
        ("typecheck/tsc_pretty.txt", 3),
        ("typecheck/tsc_watch_clean.txt", 0),
        ("mixed/tsc_and_bare_found.txt", 1),
    ],
)
def test_tsc(name: str, errors: int) -> None:
    assert parse_tsc(fixture(name)) == {"tool": "tsc", "errors": errors}


def test_tsc_variants_and_not_recognized() -> None:
    one = "src/a.ts:1:1 - error TS2304: Cannot find name 'x'.\n\nFound 1 error in src/a.ts:1\n"
    assert parse_tsc(one) == {"tool": "tsc", "errors": 1}
    same = "a.ts(1,1): error TS1: x\na.ts(2,1): error TS1: y\nFound 2 errors in the same file, starting at: a.ts:1\n"
    assert parse_tsc(same) == {"tool": "tsc", "errors": 2}
    assert parse_tsc("error TS18003: No inputs were found in config file.\n") == {
        "tool": "tsc",
        "errors": 1,
    }
    assert parse_tsc("Found 1 error.\n") is None
    assert parse_tsc("") is None
