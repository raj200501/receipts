"""Tests for receipts.verify.paths (paths are synthetic examples)."""

from __future__ import annotations

import pytest

from receipts.verify.paths import PathMatch, is_test_path, normalize_path, resolve_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/app.py", "src/app.py"),
        ("  `./src/app.py`  ", "src/app.py"),
        ("src\\app\\config.py", "src/app/config.py"),
        ("src//app/", "src/app"),
        ("src/app.py:42", "src/app.py"),
        ("src/app.py:10-20", "src/app.py"),
        ("/", "/"),
        ("", ""),
    ],
)
def test_normalize_path(raw: str, expected: str) -> None:
    assert normalize_path(raw) == expected


CANDIDATES = ["src/app/config.py", "src/app/main.py", "tests/test_main.py", "docs/main.py"]


def test_resolve_exact_beats_suffix() -> None:
    assert resolve_path("src/app/main.py", CANDIDATES) == PathMatch("src/app/main.py")


def test_resolve_unique_suffix() -> None:
    assert resolve_path("config.py", CANDIDATES) == PathMatch("src/app/config.py")
    assert resolve_path("app/config.py", CANDIDATES) == PathMatch("src/app/config.py")


def test_resolve_suffix_needs_a_component_boundary() -> None:
    assert resolve_path("onfig.py", CANDIDATES) == PathMatch(None)


def test_resolve_ambiguous_suffix() -> None:
    assert resolve_path("main.py", CANDIDATES) == PathMatch(
        None, ("docs/main.py", "src/app/main.py")
    )


def test_resolve_absolute_claim_against_relative_candidates() -> None:
    assert resolve_path("/ws/repo/src/app/config.py", CANDIDATES) == PathMatch("src/app/config.py")


def test_resolve_nothing() -> None:
    assert resolve_path("README.md", CANDIDATES) == PathMatch(None)
    assert resolve_path("", CANDIDATES) == PathMatch(None)
    assert resolve_path("x.py", []) == PathMatch(None)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_parse.py", True),
        ("tests/conftest.py", True),
        ("pkg/test/helpers.py", True),
        ("src/__tests__/app.js", True),
        ("src/test_utils.py", True),
        ("src/utils_test.py", True),
        ("web/app.test.ts", True),
        ("web/app.spec.tsx", True),
        ("src/app.py", False),
        ("src/testing.py", False),
        ("tests.md", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected
