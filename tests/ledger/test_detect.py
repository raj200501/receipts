"""Tests for output-based and command-based detection (parsers.detect, text, results)."""

from __future__ import annotations

import pytest

from receipts.ledger.parsers import (
    DerivedRuns,
    analyze_output,
    clean_lines,
    command_hints,
    is_quiet,
    is_viewer_command,
    strip_ansi,
    to_lint_run,
    to_test_run,
    to_typecheck_run,
)
from receipts.ledger.parsers.results import make_test_run

from .helpers import fixture


@pytest.mark.parametrize(
    "cmd",
    [
        "make test",
        "uv run pytest -q",
        "python -m pytest",
        "./scripts/check.sh",
        "tox -e py311",
        "cd /work/calc && uv run pytest -q 2>&1 | tail -n 40",
    ],
)
def test_pytest_output_is_found_whatever_the_wrapper(cmd: str) -> None:
    runs = analyze_output(cmd, fixture("pytest/quiet_fail.txt"), exit_code=1)
    assert [t["framework"] for t in runs.tests] == ["pytest"]
    assert runs.tests[0]["failing"] == ["tests/test_io.py::test_roundtrip"]
    assert runs.lints == () and runs.typechecks == ()


@pytest.mark.parametrize(
    ("cmd", "name", "framework"),
    [
        ("npm test", "jest/fail_npm.txt", "jest"),
        ("npm run test", "vitest/fail_npm.txt", "vitest"),
        ("npx jest", "jest/verbose_fail.txt", "jest"),
        ("node --test", "node/tap_fail.txt", "node-test"),
        ("npm test", "node/tap_pass_npm.txt", "node-test"),
        ("node --test test/", "node/spec_fail.txt", "node-test"),
        ("npm test", "mocha/fail_npm.txt", "mocha"),
        ("pnpm test", "vitest/pass.txt", "vitest"),
    ],
)
def test_js_runners_are_found(cmd: str, name: str, framework: str) -> None:
    runs = analyze_output(cmd, fixture(name), exit_code=1)
    assert [t["framework"] for t in runs.tests] == [framework]


def test_jest_writes_to_stderr() -> None:
    runs = analyze_output("npx jest", "", fixture("jest/fail_npm.txt"), exit_code=1)
    assert runs.tests[0]["failed"] == 1


def test_mocha_tap_reporter_is_labeled_mocha() -> None:
    tap = fixture("node/tap_fail.txt")
    assert analyze_output("npx mocha --reporter tap", tap).tests[0]["framework"] == "mocha"
    assert analyze_output("node --test", tap).tests[0]["framework"] == "node-test"
    npm_mocha = "> calc@1.0.0 test\n> mocha --reporter tap\n\n" + tap
    assert analyze_output("npm test", npm_mocha).tests[0]["framework"] == "mocha"


def test_native_summary_beats_junit_and_junit_alone_is_used() -> None:
    both = fixture("pytest/fail_normal.txt") + "\n" + fixture("junit/pytest_junit.xml")
    assert [t["framework"] for t in analyze_output("make test", both).tests] == ["pytest"]
    alone = analyze_output("cat-report", fixture("junit/pytest_junit.xml"))
    assert [t["framework"] for t in alone.tests] == ["junit"]


def test_pytest_beats_unittest_and_unittest_alone_is_used() -> None:
    unittest_text = fixture("unittest/fail.txt")
    assert [t["framework"] for t in analyze_output("python -m unittest", unittest_text).tests] == [
        "unittest"
    ]
    both = unittest_text + "\n" + fixture("pytest/quiet_pass.txt")
    assert [t["framework"] for t in analyze_output("make test", both).tests] == ["pytest"]


def test_make_ci_yields_lint_typecheck_and_test_runs() -> None:
    runs = analyze_output("make ci", fixture("mixed/make_ci.txt"), exit_code=0)
    assert bool(runs)
    assert [t["framework"] for t in runs.tests] == ["pytest"]
    assert runs.lints == (
        {"tool": "ruff", "errors": 0, "warnings": 0},
        {"tool": "ruff-format", "errors": 0, "warnings": 0},
    )
    assert runs.typechecks == ({"tool": "mypy", "errors": 0},)


def test_ruff_concise_lines_are_not_also_flake8() -> None:
    runs = analyze_output("make lint", fixture("mixed/make_lint_fail.txt"), exit_code=2)
    assert runs.lints == ({"tool": "ruff", "errors": 1, "warnings": 0},)
    both = analyze_output("ruff check . ; flake8 .", fixture("mixed/make_lint_fail.txt"))
    assert [lint["tool"] for lint in both.lints] == ["ruff", "flake8"]


def test_bare_found_line_goes_to_tsc_unless_ruff_is_named() -> None:
    text = fixture("mixed/tsc_and_bare_found.txt")
    runs = analyze_output("make typecheck", text, exit_code=2)
    assert runs.typechecks == ({"tool": "tsc", "errors": 1},)
    assert runs.lints == ()
    named = analyze_output("ruff check . && tsc", text, exit_code=2)
    assert [lint["tool"] for lint in named.lints] == ["ruff"]


@pytest.mark.parametrize(
    ("cmd", "stdout", "kind", "tool"),
    [
        ("npm run lint", fixture("lint/eslint_clean_npm.txt"), "lint", "eslint"),
        ("npx eslint src", "", "lint", "eslint"),
        ("flake8 src", "", "lint", "flake8"),
        ("npx tsc --noEmit", "\n", "typecheck", "tsc"),
        (
            "yarn typecheck",
            "yarn run v1.22.19\n$ vue-tsc --noEmit\nDone in 2.10s.\n",
            "typecheck",
            "tsc",
        ),
    ],
)
def test_silent_tools_count_as_clean_on_exit_zero(
    cmd: str, stdout: str, kind: str, tool: str
) -> None:
    runs = analyze_output(cmd, stdout, exit_code=0)
    found = runs.lints if kind == "lint" else runs.typechecks
    assert [(item["tool"], item["errors"]) for item in found] == [(tool, 0)]


def test_silent_tool_inference_needs_exit_zero_and_quiet_output() -> None:
    assert not analyze_output("npx eslint src", "", exit_code=1)
    assert not analyze_output("npx eslint src", "", exit_code=None)
    assert not analyze_output("npx eslint --version", "v9.9.0\n", exit_code=0)
    assert not analyze_output(
        "make lint", fixture("lint/eslint_clean_npm.txt").replace("eslint", "x"), exit_code=0
    )


@pytest.mark.parametrize(
    "cmd",
    [
        "cat out.txt",
        "tail -n 20 /tmp/pytest.log",
        "cd proj && cat log.txt | grep passed",
        "FOO=1 env cat x",
        "echo '10 passed in 0.1s'",
        "cat log > copy.txt 2>&1",
        "/bin/cat x",
    ],
)
def test_viewer_commands_derive_nothing(cmd: str) -> None:
    assert is_viewer_command(cmd)
    assert analyze_output(cmd, fixture("pytest/quiet_pass.txt"), exit_code=0) == DerivedRuns()


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest > out.txt; tail out.txt",
        "uv run pytest | tee log.txt",
        "git commit -m wip",
        "find . -name '*.py' -exec pytest {} +",
        "cat 'unbalanced",
        "",
        "(make test)",
    ],
)
def test_commands_that_run_something_are_not_viewers(cmd: str) -> None:
    assert not is_viewer_command(cmd)


def test_command_hints_reads_cmd_and_script_echo_lines() -> None:
    assert command_hints("uv run pytest -q") == frozenset({"pytest"})
    lines = clean_lines(fixture("jest/fail_npm.txt"))
    assert command_hints("npm test", lines) == frozenset({"jest"})
    assert command_hints("make", ["> not an npm header", "> tsc"]) == frozenset()
    yarn = ["yarn run v1.22.19", "$ mocha"]
    assert command_hints("yarn test", yarn) == frozenset({"mocha"})
    assert command_hints("node --test --watch") == frozenset({"node-test"})
    assert "pyright" in command_hints("basedpyright src")


def test_is_quiet() -> None:
    assert is_quiet([])
    assert is_quiet(["", "> web@1.0.0 lint", "> eslint src", "npm warn deprecated x", "  "])
    assert not is_quiet(["> web@1.0.0 lint", "/work/web/src/app.js"])


def test_strip_ansi_and_clean_lines() -> None:
    assert strip_ansi("\x1b[31mred\x1b(B\x1b[m \x1b]8;;http://x\x07link\x1b]8;;\x07 \x1bMok") == (
        "red link ok"
    )
    assert clean_lines("a  \r\nprogress 10%\rprogress 100%\r\nb\r\n\r\n") == [
        "a",
        "progress 100%",
        "b",
        "",
        "",
    ]
    assert clean_lines("\r\r") == [""]


def test_result_converters_add_command_seq_and_source() -> None:
    parsed = make_test_run(
        "pytest",
        passed=1,
        failed=1,
        errors=0,
        skipped=0,
        failing=["t::a"],
        cases=[{"name": "t::a", "outcome": "failed"}, {"name": "t::b", "outcome": "passed"}],
    )
    data = to_test_run(parsed, 7, "agent")
    assert data["command_seq"] == 7 and data["source"] == "agent" and data["total"] == 2
    assert data["cases"] == parsed.get("cases")
    assert data["failing"] is not parsed["failing"]
    no_cases = to_test_run(
        make_test_run("jest", passed=0, failed=0, errors=0, skipped=0, failing=[]), 1, "snapshot"
    )
    assert "cases" not in no_cases and no_cases["collection_error"] is False
    assert to_lint_run({"tool": "ruff", "errors": 2, "warnings": 0}, 3, "agent") == {
        "tool": "ruff",
        "command_seq": 3,
        "errors": 2,
        "warnings": 0,
        "source": "agent",
    }
    assert to_typecheck_run({"tool": "mypy", "errors": 0}, 4, "snapshot") == {
        "tool": "mypy",
        "command_seq": 4,
        "errors": 0,
        "source": "snapshot",
    }


def test_unrecognized_output_derives_nothing() -> None:
    runs = analyze_output("make build", "gcc -o app main.c\nlinking...\n", exit_code=0)
    assert not runs
    assert runs == DerivedRuns()
