"""Tests for receipts.verify.commands (commands are synthetic examples)."""

from __future__ import annotations

import pytest

from receipts.verify.commands import (
    command_is,
    command_matches,
    core_segments,
    describe,
    generic_kind,
    segment_matches,
    split_command,
)


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("pytest -q", [("pytest", "-q")]),
        ("uv run --no-sync pytest -q tests/", [("pytest", "-q", "tests")]),
        ("python3 -m pytest", [("pytest",)]),
        ("uv run python -m pytest ./tests", [("pytest", "tests")]),
        (".venv/bin/pytest", [("pytest",)]),
        ("cd app && npm run test", [("npm", "test")]),
        ("npm t", [("npm", "test")]),
        ("npx -y vitest run", [("vitest", "run")]),
        ("CI=1 FOO=bar time pytest", [("pytest",)]),
        ("env pytest", [("pytest",)]),
        (
            "ruff check . && mypy src; pytest | tee out",
            [
                ("ruff", "check", "."),
                ("mypy", "src"),
                ("pytest",),
                ("tee", "out"),
            ],
        ),
        ("'pytest' \"-q\" `x`", [("pytest", "-q", "x")]),
        ("PyTest -Q", [("pytest", "-q")]),
        ("pytest -q 2>&1", [("pytest", "-q")]),
        ("pytest -q > out.txt 2> err.txt", [("pytest", "-q")]),
        ("pytest -q >out.txt <in &>all", [("pytest", "-q")]),
        ("python script.py", [("python", "script.py")]),
        ("npx", [("npx",)]),
        ("", []),
        ("cd sub", []),
        ("FOO=1", []),
    ],
)
def test_split_command(cmd: str, expected: list[tuple[str, ...]]) -> None:
    assert split_command(cmd) == expected


def test_segment_matches_allows_extra_recorded_tokens() -> None:
    assert segment_matches(("pytest",), ("pytest", "-q", "tests"))
    assert segment_matches(("pytest", "-q"), ("pytest", "-q", "-x"))
    assert not segment_matches(("pytest", "-v"), ("pytest", "-q"))
    assert not segment_matches(("pytest", "tests/a.py"), ("pytest", "tests/b.py"))
    assert not segment_matches(("ruff",), ("mypy",))
    assert not segment_matches((), ("pytest",))


@pytest.mark.parametrize(
    ("claimed", "recorded", "expected"),
    [
        ("pytest", "uv run --no-sync python -m pytest -q", True),
        ("python -m pytest -q", "pytest -q --tb=short", True),
        ("`ruff check .`", "cd /ws && ruff check . --fix", True),
        ("ruff check . && mypy src", "ruff check . && mypy src --strict", True),
        ("ruff check . && mypy src", "ruff check .", False),
        ("npm run test", "npm test", True),
        ("npx jest", "jest --ci", True),
        ("pytest tests/test_a.py", "pytest tests/test_b.py", False),
        ("", "pytest", False),
        ("pytest -q | tail -20", "pytest -q", True),
        ("grep -r todo src", "grep -r todo src", True),
        ("grep -r todo src", "pytest", False),
    ],
)
def test_command_matches(claimed: str, recorded: str, expected: bool) -> None:
    assert command_matches(claimed, recorded) is expected


@pytest.mark.parametrize(
    ("claimed", "expected"),
    [
        ("the tests", "test"),
        ("tests", "test"),
        ("the full test suite", "test"),
        ("all the unit tests", "test"),
        ("The Linter", "lint"),
        ("linting", "lint"),
        ("the type checker", "typecheck"),
        ("type-checks", "typecheck"),
        ("the build", "build"),
        ("pytest", None),
        ("ruff check .", None),
    ],
)
def test_generic_kind(claimed: str, expected: str | None) -> None:
    assert generic_kind(claimed) == expected


@pytest.mark.parametrize(
    ("cmd", "test", "lint", "typecheck", "build"),
    [
        ("pytest -q", True, False, False, False),
        ("npm test", True, False, False, False),
        ("go test ./...", True, False, False, False),
        ("make test", True, False, False, False),
        ("node --test", True, False, False, False),
        ("ruff check .", False, True, False, False),
        ("ruff format .", False, False, False, False),
        ("ruff format --check .", False, True, False, False),
        ("npm run lint", False, True, False, False),
        ("make lint", False, True, False, False),
        ("mypy --strict src", False, False, True, False),
        ("npm run typecheck", False, False, True, False),
        ("make typecheck", False, False, True, False),
        ("tsc --noEmit", False, False, True, True),
        ("npm run build", False, False, False, True),
        ("python -m build", False, False, False, True),
        ("uv build", False, False, False, True),
        ("make build", False, False, False, True),
        ("cargo build --release", False, False, False, True),
        ("ls -la", False, False, False, False),
    ],
)
def test_command_is(cmd: str, test: bool, lint: bool, typecheck: bool, build: bool) -> None:
    assert command_is("test", cmd) is test
    assert command_is("lint", cmd) is lint
    assert command_is("typecheck", cmd) is typecheck
    assert command_is("build", cmd) is build


def test_describe_joins_segments() -> None:
    assert describe([("ruff", "check"), ("pytest",)]) == "ruff check && pytest"


def test_core_segments_drops_output_filters_unless_alone() -> None:
    assert core_segments([("pytest",), ("tail", "-20"), ("grep", "x")]) == [("pytest",)]
    assert core_segments([("grep", "-r", "x")]) == [("grep", "-r", "x")]
    assert core_segments([]) == []
