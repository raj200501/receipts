"""Tests for receipts.claims.patterns. Every phrase here is hand-written test input."""

from __future__ import annotations

import pytest

from receipts.claims.patterns import (
    PatternHit,
    UnitMatches,
    command_kinds,
    command_param,
    dependency_param,
    generic_command,
    hit_claim,
    match_unit,
    match_units,
    path_param,
    pattern_claims,
)
from receipts.claims.segment import Unit, segment
from receipts.claims.types import Claim, ClaimType

Expected = list[tuple[str, dict[str, object], bool]]


def found(text: str) -> Expected:
    return [(c.type.value, dict(c.params), c.negated) for c in pattern_claims(text)]


# --- params ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("`src/app.py`", "src/app.py"),
        ("src/app.py:42", "src/app.py"),
        ("src/app.py:10-20", "src/app.py"),
        ("src/app.ts#L12-L30", "src/app.ts"),
        ("tests/test_io.py::test_roundtrip", "tests/test_io.py"),
        ("(docs/usage.md).", "docs/usage.md"),
        ("'config.yaml'", "config.yaml"),
        (".gitignore", ".gitignore"),
        ("src/.env", "src/.env"),
        ("app.env", None),
        (".env.example", ".env.example"),
        ("settings.example", None),
        ("config.toml.example", "config.toml.example"),
        ("README", "README.md"),
        ("docs/README", "docs/README.md"),
        ("Makefile", "Makefile"),
        ("pyproject", "pyproject.toml"),
        ("Node.js", None),
        ("https://example.com/a.md", None),
        ("--json", None),
        ("@scope/pkg", None),
        ("src/", None),
        ("src/*.py", None),
        ("parse_range", None),
        ("v1.2.3", None),
        ("...py", None),
        ("", None),
    ],
)
def test_path_param(raw: str, expected: str | None) -> None:
    assert path_param(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pytest -q", "pytest -q"),
        ("$ npm test", "npm test"),
        ("sudo make test", "sudo make test"),
        ("FOO=1 python3.12 -m pytest", "FOO=1 python3.12 -m pytest"),
        ("./scripts/check", "./scripts/check"),
        ("bin/run.sh --fast", "bin/run.sh --fast"),
        ("run_tests", "the tests"),
        ("run_tests()", "the tests"),
        ("FOO=1", None),
        ("parse_range", None),
        ("src/app.py", None),
        ("", None),
    ],
)
def test_command_param(raw: str, expected: str | None) -> None:
    assert command_param(raw) == expected


@pytest.mark.parametrize(
    ("command", "kinds"),
    [
        ("pytest -q", {"test"}),
        ("uv run --no-sync python -m pytest", {"test"}),
        ("npm test", {"test"}),
        ("npm run test", {"test"}),
        ("pnpm --filter ui test", {"test"}),
        ("pnpm --filter=ui build", {"build"}),
        ("go test ./...", {"test"}),
        ("make test lint", {"test", "lint"}),
        ("ruff check . && mypy src", {"lint", "typecheck"}),
        ("ruff format .", set()),
        ("ruff format --check .", {"lint"}),
        ("npx tsc --noEmit", {"typecheck"}),
        ("npm run lint", {"lint"}),
        ("yarn typecheck", {"typecheck"}),
        ("npm run build", {"build"}),
        ("cargo build --release", {"build"}),
        ("webpack", {"build"}),
        ("cd app && run_tests", {"test"}),
        ("time env CI=1 pytest", {"test"}),
        ("git status", set()),
    ],
)
def test_command_kinds(command: str, kinds: set[str]) -> None:
    assert command_kinds(command) == frozenset(kinds)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("`requests>=2.32`", ("requests", "2.32")),
        ("lodash@4.17.21", ("lodash", "4.17.21")),
        ("@types/node@20.11.5", ("@types/node", "20.11.5")),
        ("httpx[http2]==0.27.0", ("httpx", "0.27.0")),
        ("numpy<2,>=1.26", ("numpy", "2")),
        ("typescript ^5.4", ("typescript", "5.4")),
        ("django", ("django", None)),
        ("the parser", None),
        ("tests", None),
        ("setup.py", None),
        ("src/pkg", None),
        ("MAX_RETRIES", None),
        ("", None),
    ],
)
def test_dependency_param(raw: str, expected: tuple[str, str | None] | None) -> None:
    assert dependency_param(raw) == expected


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("the tests", ("the tests", False)),
        ("all of the tests", ("all the tests", False)),
        ("The full test suite.", ("the full test suite", True)),
        ("the unit tests", ("the unit tests", True)),
        ("the e2e tests", ("the tests", True)),
        ("a quick test run", None),
        ("some tests", ("the tests", True)),
        ("the pytest tests", ("pytest", False)),
        ("the linter", ("the linter", False)),
        ("the type checker", ("the type checker", False)),
        ("the typechecker", ("the type checker", False)),
        ("the builds", ("the builds", False)),
        ("npm run build", None),
        ("42 tests", None),
        ("the parser", None),
    ],
)
def test_generic_command(phrase: str, expected: tuple[str, bool] | None) -> None:
    assert generic_command(phrase) == expected


# --- units and claims ---------------------------------------------------------------------


def test_pattern_hit_key_ignores_negation_and_anchor() -> None:
    hit = PatternHit(ClaimType.TESTS_PASS, {"scope": "unit"}, True, (0, 4))
    same = PatternHit(ClaimType.TESTS_PASS, {"scope": "unit"}, False, (5, 9))
    assert hit.key() == same.key() == (ClaimType.TESTS_PASS, (("scope", "unit"),))


def test_match_units_and_hit_claim() -> None:
    report = "Updated `a.py`.\n\nHello there."
    matches = match_units(segment(report))
    assert [type(m) for m in matches] == [UnitMatches, UnitMatches]
    first, second = matches
    assert second.hits == ()
    (hit,) = first.hits
    claim = hit_claim(first.unit, hit, "c7")
    assert claim == Claim(
        "c7",
        ClaimType.FILE_MODIFIED,
        "Updated `a.py`.",
        (0, 15),
        {"path": "a.py"},
        False,
        "pattern",
    )


def test_identical_claims_of_a_unit_are_kept_once() -> None:
    unit = Unit("All tests pass (all tests pass).", (0, 32), "sentence")
    assert [h.type for h in match_unit(unit)] == [ClaimType.TESTS_PASS]


def test_pattern_claims_number_claims_in_report_order() -> None:
    claims = pattern_claims("Done. All 3 tests pass.\n\n- Removed `old.py`.")
    assert [(c.claim_id, c.type) for c in claims] == [
        ("c0", ClaimType.TASK_COMPLETE),
        ("c1", ClaimType.TEST_COUNT),
        ("c2", ClaimType.FILE_DELETED),
    ]


def test_context_labels_drive_bare_list_items() -> None:
    report = (
        "## Bug fixes\n- Empty input no longer crashes `parse`\n\n"
        "## New features\n- A `--quiet` mode\n\n"
        "New dependencies:\n- `httpx`, `respx`\n\n"
        "**Files changed:**\n- `src/app.py`\n- `src/new.py`: new file\n- `src/old.py`: removed\n"
    )
    assert found(report) == [
        ("bug_fixed", {"description": "Empty input no longer crashes `parse`"}, False),
        ("feature_implemented", {"description": "A `--quiet` mode"}, False),
        ("dependency_added", {"name": "httpx"}, False),
        ("dependency_added", {"name": "respx"}, False),
        ("file_modified", {"path": "src/app.py"}, False),
        ("file_created", {"path": "src/new.py"}, False),
        ("file_deleted", {"path": "src/old.py"}, False),
    ]


def test_commands_listed_under_a_verification_heading() -> None:
    report = "### How I verified\n- `pytest -q`\n- `ruff check .`\n\n### Notes\n- `pytest -q`\n"
    assert found(report) == [
        ("ran_command", {"command": "pytest -q"}, False),
        ("ran_command", {"command": "ruff check ."}, False),
    ]


def test_previous_unit_gives_the_anaphora_its_subject() -> None:
    assert found("Added tests for the parser. They pass.") == [
        ("tests_added", {"target": "the parser"}, False),
        ("tests_pass", {}, False),
    ]
    assert found("Updated the parser. They pass.") == []


# --- rules ---------------------------------------------------------------------------------

#: Hand-written phrases and the claims the pattern rules must find in them, in order. Each
#: row was reviewed by hand; an empty list means the phrase must yield no pattern claim
#: (advice, hedges, history, descriptions of code, or phrasing left to the model).
RULE_CASES: list[tuple[str, Expected]] = [
    ("All tests pass.", [("tests_pass", {"scope": "all"}, False)]),
    ("All 42 tests passed.", [("test_count", {"passed": 42, "total": 42}, False)]),
    ("12/13 tests pass.", [("test_count", {"passed": 12, "total": 13}, False)]),
    ("The test suite is green.", [("tests_pass", {}, False)]),
    ("I ran `pytest -q`.", [("ran_command", {"command": "pytest -q"}, False)]),
    ("Ran the linter.", [("ran_command", {"command": "the linter"}, False)]),
    (
        "Updated `src/config.py` to read the timeout from the environment.",
        [("file_modified", {"path": "src/config.py"}, False)],
    ),
    ("Created docs/usage.md.", [("file_created", {"path": "docs/usage.md"}, False)]),
    ("Removed the unused helper in utils.py.", [("file_modified", {"path": "utils.py"}, False)]),
    ("I didn't touch the CLI.", []),
    (
        "Added `requests>=2.32` as a dependency.",
        [("dependency_added", {"name": "requests", "version": "2.32"}, False)],
    ),
    (
        "Bumped lodash to 4.17.21.",
        [("dependency_updated", {"name": "lodash", "version": "4.17.21"}, False)],
    ),
    (
        "Fixed the off-by-one in parse_range.",
        [("bug_fixed", {"description": "the off-by-one in parse_range"}, False)],
    ),
    (
        "Implemented the --json flag.",
        [("feature_implemented", {"description": "the --json flag"}, False)],
    ),
    ("ruff reports no issues.", [("lint_clean", {"tool": "ruff"}, False)]),
    ("mypy passes with no errors.", [("typecheck_clean", {"tool": "mypy"}, False)]),
    ("The build succeeds.", [("build_succeeds", {}, False)]),
    (
        "I couldn't get the integration test to run because Postgres isn't available.",
        [("could_not", {"description": "get the integration test to run"}, False)],
    ),
    ("Done.", [("task_complete", {}, False)]),
    ("Everything is implemented and working.", [("task_complete", {}, False)]),
    ("Tests still fail.", [("tests_pass", {}, True)]),
    ("I did not run the linter.", [("ran_command", {"command": "the linter"}, True)]),
    (
        "The tests could not be run.",
        [("could_not", {"description": "The tests could not be run"}, False)],
    ),
    ("The suite isn't passing.", [("tests_pass", {}, True)]),
    ("1 test is still failing.", [("tests_pass", {}, True)]),
    ("Tests: 42 passed, 0 failed", [("test_count", {"passed": 42, "failed": 0}, False)]),
    (
        "`pytest` -> 3 failed, 39 passed",
        [
            ("ran_command", {"command": "pytest"}, False),
            ("test_count", {"passed": 39, "failed": 3}, False),
        ],
    ),
    ("Before my change, 3 tests failed.", []),
    (
        "The build (`npm run build`) completes without errors.",
        [
            ("build_succeeds", {"tool": "npm run build"}, False),
            ("ran_command", {"command": "npm run build"}, False),
        ],
    ),
    ("The old implementation fixed the seed at 42.", []),
    ("Once the build passes, deploy with `make deploy`.", []),
    ("Tests were not added.", [("tests_added", {}, True)]),
    ("No tests were added.", [("tests_added", {}, True)]),
    ("I did not add any tests.", [("tests_added", {}, True)]),
    (
        "Unfortunately the e2e suite can't run here since Docker isn't available.",
        [("could_not", {"description": "the e2e suite can't run here"}, False)],
    ),
    (
        "I haven't been able to verify the Windows path handling.",
        [("could_not", {"description": "verify the Windows path handling"}, False)],
    ),
    ("Applied edit to src/app.py", [("file_modified", {"path": "src/app.py"}, False)]),
    ("The fix is in `src/ranges.py`.", [("file_modified", {"path": "src/ranges.py"}, False)]),
    ("Made changes to `src/app.py`.", [("file_modified", {"path": "src/app.py"}, False)]),
    (
        "In `src/app.py`, added a `--json` flag.",
        [
            ("file_modified", {"path": "src/app.py"}, False),
            ("feature_implemented", {"description": "a `--json` flag"}, False),
        ],
    ),
    (
        "Type checking passes (`mypy --strict src`).",
        [
            ("typecheck_clean", {"tool": "mypy"}, False),
            ("ran_command", {"command": "mypy --strict src"}, False),
        ],
    ),
    ("If mypy passes, we're good.", []),
    ("I didn't run the tests.", [("ran_command", {"command": "the tests"}, True)]),
    (
        "Fixed the bug, added a test, and ran the suite.",
        [
            ("bug_fixed", {"description": "the bug"}, False),
            ("tests_added", {}, False),
            ("ran_command", {"command": "the suite"}, False),
        ],
    ),
    ("I ran the tests.", [("ran_command", {"command": "the tests"}, False)]),
    ("Ran tests.", [("ran_command", {"command": "tests"}, False)]),
    (
        "I ran pytest and mypy.",
        [
            ("ran_command", {"command": "pytest"}, False),
            ("ran_command", {"command": "mypy"}, False),
        ],
    ),
    (
        "Ran `npm test` and `npm run lint`.",
        [
            ("ran_command", {"command": "npm test"}, False),
            ("ran_command", {"command": "npm run lint"}, False),
        ],
    ),
    (
        "Tests were run with `pytest -q`.",
        [
            ("ran_command", {"command": "tests"}, False),
            ("ran_command", {"command": "pytest -q"}, False),
        ],
    ),
    ("The full test suite was not run.", []),
    ("The tests were not run.", [("ran_command", {"command": "the tests"}, True)]),
    ("I re-ran the failing test.", [("ran_command", {"command": "the test"}, False)]),
    ("I ran into a problem with the fixtures.", []),
    ("I ran out of time.", []),
    ("This script runs the tests.", []),
    (
        "Running `pytest` now shows 12 passed.",
        [("ran_command", {"command": "pytest"}, False), ("test_count", {"passed": 12}, False)],
    ),
    (
        "After running `npm test`, all 31 tests pass.",
        [
            ("ran_command", {"command": "npm test"}, False),
            ("test_count", {"passed": 31, "total": 31}, False),
        ],
    ),
    (
        "I verified the fix by running `pytest tests/test_dates.py`.",
        [("ran_command", {"command": "pytest tests/test_dates.py"}, False)],
    ),
    (
        "pytest: 12 passed",
        [("ran_command", {"command": "pytest"}, False), ("test_count", {"passed": 12}, False)],
    ),
    (
        "`make test` passes.",
        [("ran_command", {"command": "make test"}, False), ("tests_pass", {}, False)],
    ),
    ("All green.", [("tests_pass", {}, False)]),
    ("Everything passes.", [("tests_pass", {}, False)]),
    ("CI is green.", []),
    ("2 tests fail.", [("tests_pass", {}, True)]),
    ("`test_foo` fails.", [("tests_pass", {"scope": "test_foo"}, True)]),
    ("12 of 14 tests pass.", [("test_count", {"passed": 12, "total": 14}, False)]),
    (
        "Ran 14 tests, 12 passed, 2 failed.",
        [("test_count", {"passed": 12, "total": 14, "failed": 2}, False)],
    ),
    ("The test suite passes except for `test_slow_network`.", [("tests_pass", {}, True)]),
    ("None of the tests fail.", [("tests_pass", {}, False)]),
    ("No tests fail.", [("tests_pass", {}, False)]),
    ("Tests are still red.", [("tests_pass", {}, True)]),
    ("I haven't run the tests yet.", [("ran_command", {"command": "the tests"}, True)]),
    ("The tests didn't run because of an import error.", [("tests_pass", {}, True)]),
    ("Coverage is at 94%.", []),
    (
        "Installed `pytest-cov` as a dev dependency.",
        [("dependency_added", {"name": "pytest-cov"}, False)],
    ),
    (
        "Added `zod@3.23.8` to `package.json`.",
        [
            ("file_modified", {"path": "package.json"}, False),
            ("dependency_added", {"name": "zod", "version": "3.23.8"}, False),
        ],
    ),
    (
        "Upgraded Django to 5.0.",
        [("dependency_updated", {"name": "Django", "version": "5.0"}, False)],
    ),
    (
        "Bumped `typescript` to `^5.4.5`.",
        [("dependency_updated", {"name": "typescript", "version": "5.4.5"}, False)],
    ),
    (
        "Removed the unused `lodash` dependency.",
        [("dependency_removed", {"name": "lodash"}, False)],
    ),
    ("Uninstalled `moment`.", [("dependency_removed", {"name": "moment"}, False)]),
    ("Removed the deprecated `--legacy` flag.", []),
    (
        "Added support for YAML config files.",
        [("feature_implemented", {"description": "YAML config files"}, False)],
    ),
    (
        "The `--json` flag is now supported.",
        [("feature_implemented", {"description": "The `--json` flag"}, False)],
    ),
    (
        "The CLI now supports a `--quiet` option.",
        [
            (
                "feature_implemented",
                {"description": "The CLI now supports a `--quiet` option"},
                False,
            )
        ],
    ),
    (
        "Pagination is not implemented yet.",
        [("feature_implemented", {"description": "Pagination"}, True)],
    ),
    (
        "Resolved #42: dates before 1970 now parse correctly.",
        [("bug_fixed", {"description": "#42"}, False)],
    ),
    (
        "The crash on empty input is fixed.",
        [("bug_fixed", {"description": "The crash on empty input"}, False)],
    ),
    (
        "The memory leak is still present.",
        [("bug_fixed", {"description": "The memory leak"}, True)],
    ),
    (
        "Fixes the race condition in `worker.py`.",
        [
            ("bug_fixed", {"description": "the race condition in `worker.py`"}, False),
            ("file_modified", {"path": "worker.py"}, False),
        ],
    ),
    ("All requirements are met.", [("task_complete", {}, False)]),
    ("The implementation is not complete yet.", [("task_complete", {}, True)]),
    ("Ready for review.", [("task_complete", {}, False)]),
    ("I think the change is complete, but please double-check.", []),
    ("Deleted the obsolete fixtures in `tests/fixtures/`.", []),
    ("Wrote a short note in `CHANGELOG.md`.", [("file_modified", {"path": "CHANGELOG.md"}, False)]),
    (
        "Added a `pyproject.toml` with ruff settings.",
        [("file_created", {"path": "pyproject.toml"}, False)],
    ),
    ("`src/legacy.py` was removed.", [("file_deleted", {"path": "src/legacy.py"}, False)]),
    (
        "`docs/usage.md` and `README.md` were updated.",
        [
            ("file_modified", {"path": "docs/usage.md"}, False),
            ("file_modified", {"path": "README.md"}, False),
        ],
    ),
    ("I'd recommend running the full test suite before merging.", []),
    ("If the tests fail, check the fixture path.", []),
    ("The `--json` flag outputs one object per line.", []),
    (
        "This PR adds a `--dry-run` option.",
        [("feature_implemented", {"description": "a `--dry-run` option"}, False)],
    ),
    ("Tests should pass now.", []),
    ("Using Node.js 20 and Python 3.11.", []),
    ("See https://example.com/docs/setup.md for details.", []),
    ("Read `config.yaml` to understand the settings.", []),
    (
        "Edited `src/app.py`, `src/cli.py`, and `tests/test_cli.py`.",
        [
            ("file_modified", {"path": "src/app.py"}, False),
            ("file_modified", {"path": "src/cli.py"}, False),
            ("file_modified", {"path": "tests/test_cli.py"}, False),
        ],
    ),
    (
        "Added a test to `tests/test_cli.py`.",
        [
            ("tests_added", {"path": "tests/test_cli.py"}, False),
            ("file_modified", {"path": "tests/test_cli.py"}, False),
        ],
    ),
    (
        "I ran `pytest tests/test_cli.py -k json` and it passed.",
        [
            ("ran_command", {"command": "pytest tests/test_cli.py -k json"}, False),
            ("tests_pass", {}, False),
        ],
    ),
    (
        "`pytest` -> 3 failed, 39 passed, 1 skipped",
        [
            ("ran_command", {"command": "pytest"}, False),
            ("test_count", {"passed": 39, "failed": 3}, False),
        ],
    ),
    ("Run `make lint` to check formatting.", []),
    ("Please run `npm install` first.", []),
    ('I skipped the slow tests (`pytest -m "not slow"`).', []),
    (
        "Moved `scripts/setup.sh` to `bin/setup.sh`.",
        [
            ("file_deleted", {"path": "scripts/setup.sh"}, False),
            ("file_created", {"path": "bin/setup.sh"}, False),
        ],
    ),
    (
        "I added a `.env.example` file with the required variables.",
        [("file_created", {"path": ".env.example"}, False)],
    ),
    (
        "Kept `legacy/api.py` as-is for backward compatibility.",
        [("file_unchanged", {"path": "legacy/api.py"}, False)],
    ),
    ("Tests: 12/12 passing", [("test_count", {"passed": 12, "total": 12}, False)]),
    (
        "Typecheck: `pyright` -> 0 errors, 0 warnings",
        [
            ("ran_command", {"command": "pyright"}, False),
            ("typecheck_clean", {"tool": "pyright"}, False),
        ],
    ),
    (
        "Couldn't reproduce the flaky failure locally.",
        [("could_not", {"description": "reproduce the flaky failure locally"}, False)],
    ),
    (
        "Ran out of time before adding the CSV exporter.",
        [("could_not", {"description": "adding the CSV exporter"}, False)],
    ),
    (
        "I updated the `Makefile` and the `Dockerfile` to use Python 3.12.",
        [
            ("file_modified", {"path": "Makefile"}, False),
            ("file_modified", {"path": "Dockerfile"}, False),
        ],
    ),
    ("test_parse_empty fails.", [("tests_pass", {"scope": "test_parse_empty"}, True)]),
    (
        "`tests/test_io.py::test_roundtrip` fails.",
        [("tests_pass", {"scope": "tests/test_io.py::test_roundtrip"}, True)],
    ),
    ("`src/cart.test.ts` passes.", [("tests_pass", {"scope": "src/cart.test.ts"}, False)]),
    ("`foo.py` fails.", []),
    ("`test_slow` passes.", [("tests_pass", {"scope": "test_slow"}, False)]),
    ("All tests pass except `test_slow`.", [("tests_pass", {}, True)]),
    ("Not all tests pass yet.", [("tests_pass", {}, True)]),
    ("Some tests are failing.", [("tests_pass", {}, True)]),
    ("There are still a few failures.", [("tests_pass", {}, True)]),
    ("The tests don't pass yet.", [("tests_pass", {}, True)]),
    ("The tests did not pass before my change.", []),
    ("The tests no longer fail.", [("tests_pass", {}, False)]),
    (
        "Added tests for the parser. They pass.",
        [("tests_added", {"target": "the parser"}, False), ("tests_pass", {}, False)],
    ),
    ("Success: no issues found in 12 source files", [("typecheck_clean", {}, False)]),
    ("`black --check .` is clean.", [("ran_command", {"command": "black --check ."}, False)]),
    (
        "Lint (`ruff check .`): clean",
        [
            ("lint_clean", {"tool": "ruff"}, False),
            ("ran_command", {"command": "ruff check ."}, False),
        ],
    ),
    ("ruff reports 0 errors.", [("lint_clean", {"tool": "ruff"}, False)]),
    ("3 lint errors remain.", [("lint_clean", {}, True)]),
    ("No lint errors.", [("lint_clean", {}, False)]),
    (
        "`tsc` compiles cleanly.",
        [("ran_command", {"command": "tsc"}, False), ("typecheck_clean", {"tool": "tsc"}, False)],
    ),
    ("The build (see notes) passes.", [("build_succeeds", {}, False)]),
    ("make build succeeds.", [("build_succeeds", {"tool": "make build"}, False)]),
    ("If the project builds cleanly, ship it.", []),
    ("The project does not build.", [("build_succeeds", {}, True)]),
    (
        "Added `httpx` and `respx` to dev dependencies.",
        [
            ("dependency_added", {"name": "httpx"}, False),
            ("dependency_added", {"name": "respx"}, False),
        ],
    ),
    ("You need to add `httpx` as a dependency.", []),
    ("Updated foo to 2.", []),
    ("Bumped the `pydantic` dependency.", [("dependency_updated", {"name": "pydantic"}, False)]),
    (
        "Upgraded `react@18.3.1`.",
        [("dependency_updated", {"name": "react", "version": "18.3.1"}, False)],
    ),
    (
        "Pinned `numpy==1.26.4`.",
        [("dependency_updated", {"name": "numpy", "version": "1.26.4"}, False)],
    ),
    (
        "| Updated `a.py` and `b.py` | done |",
        [("file_modified", {"path": "a.py"}, False), ("file_modified", {"path": "b.py"}, False)],
    ),
    ("Changed the parser from `a.py` to `b.py`.", []),
    ("Moved the helper into `utils.py`.", [("file_modified", {"path": "utils.py"}, False)]),
    ("Updated `tests/test_x.py::test_y`.", [("file_modified", {"path": "tests/test_x.py"}, False)]),
    ("No changes to `settings.py`.", [("file_unchanged", {"path": "settings.py"}, False)]),
    (
        "Ran the tests and the linter: both pass.",
        [
            ("ran_command", {"command": "the tests"}, False),
            ("ran_command", {"command": "the linter"}, False),
            ("tests_pass", {}, False),
            ("lint_clean", {}, False),
        ],
    ),
    (
        "Ran `pytest` and `ruff check .`: both fail.",
        [
            ("ran_command", {"command": "pytest"}, False),
            ("ran_command", {"command": "ruff check ."}, False),
            ("tests_pass", {}, True),
            ("lint_clean", {"tool": "ruff"}, True),
        ],
    ),
    ("✅ `foo bar`", []),
    (
        "❌ `npm run build` (missing env var)",
        [
            ("ran_command", {"command": "npm run build"}, False),
            ("build_succeeds", {"tool": "npm run build"}, True),
        ],
    ),
    (
        "✔ `pytest -q`",
        [("ran_command", {"command": "pytest -q"}, False), ("tests_pass", {}, False)],
    ),
    (
        "I couldn't run `pytest` (missing deps), but ruff is clean.",
        [
            ("could_not", {"description": "run `pytest`"}, False),
            ("lint_clean", {"tool": "ruff"}, False),
        ],
    ),
    (
        "mypy: `Success: no issues found in 3 source files`",
        [("ran_command", {"command": "mypy"}, False), ("typecheck_clean", {"tool": "mypy"}, False)],
    ),
    (
        "Ran `npm test -- --run`: 12 passing.",
        [
            ("ran_command", {"command": "npm test -- --run"}, False),
            ("test_count", {"passed": 12}, False),
        ],
    ),
    (
        "I ran the unit and integration tests.",
        [
            ("ran_command", {"command": "the unit tests"}, False),
            ("ran_command", {"command": "the integration tests"}, False),
        ],
    ),
    ("I did not run the unit tests.", []),
    ("Ran a quick test run.", [("ran_command", {"command": "the test"}, False)]),
    ("Ran the pytest tests.", [("ran_command", {"command": "pytest"}, False)]),
    (
        "I ran the type checker and the build.",
        [
            ("ran_command", {"command": "the type checker"}, False),
            ("ran_command", {"command": "the build"}, False),
        ],
    ),
    ("Running the linter shows 2 warnings.", [("ran_command", {"command": "the linter"}, False)]),
    (
        "pytest -> 12 passed",
        [("ran_command", {"command": "pytest"}, False), ("test_count", {"passed": 12}, False)],
    ),
    (
        "The tests were executed with `npm test`.",
        [
            ("ran_command", {"command": "the tests"}, False),
            ("ran_command", {"command": "npm test"}, False),
        ],
    ),
]


@pytest.mark.parametrize(("text", "expected"), RULE_CASES, ids=[t[:50] for t, _ in RULE_CASES])
def test_rule_cases(text: str, expected: Expected) -> None:
    assert found(text) == expected
