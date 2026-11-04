"""Tests for the JUnit XML, node --test, Jest, Vitest and Mocha parsers (hand-written fixtures)."""

from __future__ import annotations

import pytest

from receipts.ledger.parsers.junit import parse_junit
from receipts.ledger.parsers.node import parse_jest, parse_mocha, parse_node_test, parse_vitest
from receipts.ledger.parsers.results import ParsedTestRun

from .helpers import fixture


def _counts(run: ParsedTestRun | None) -> tuple[int, int, int, int, int]:
    assert run is not None
    assert run["total"] == run["passed"] + run["failed"] + run["errors"] + run["skipped"]
    return run["passed"], run["failed"], run["errors"], run["skipped"], run["total"]


def test_junit_pytest_report() -> None:
    run = parse_junit(fixture("junit/pytest_junit.xml"))
    assert _counts(run) == (2, 1, 1, 1, 5)
    assert run is not None
    assert run["framework"] == "junit"
    assert run["failing"] == ["tests.test_calc.test_div", "tests.test_db.test_connect"]
    assert run["collection_error"] is False
    assert run.get("cases", [])[4] == {"name": "tests.test_net.test_fetch", "outcome": "skipped"}


def test_junit_many_suites_and_repeated_classnames() -> None:
    run = parse_junit(fixture("junit/jest_junit.xml"))
    assert _counts(run) == (3, 1, 0, 1, 5)
    assert run is not None
    assert run["failing"] == ["Calculator divides by zero"]


def test_junit_single_testsuite_root() -> None:
    run = parse_junit(fixture("junit/single_suite.xml"))
    assert _counts(run) == (3, 0, 0, 0, 3)
    assert run is not None
    assert next(c["name"] for c in run.get("cases", [])) == "slugify lowercases"


def test_junit_collection_failure() -> None:
    run = parse_junit(fixture("junit/collection_error.xml"))
    assert _counts(run) == (0, 0, 1, 0, 1)
    assert run is not None
    assert run["failing"] == ["tests.test_cart"]
    assert run["collection_error"] is True


def test_junit_embedded_in_other_output_with_namespace() -> None:
    text = (
        "> web@1.0.0 test\n> vitest run --reporter=junit\n"
        '<testsuites xmlns="urn:example"><testsuite name="s">'
        '<testcase classname="a" name="b"/><testcase name="c"><failure/></testcase>'
        "</testsuite></testsuites>\nnpm error code 1\n"
    )
    run = parse_junit(text)
    assert _counts(run) == (1, 1, 0, 0, 2)
    assert run is not None
    assert run["failing"] == ["c"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no xml here",
        fixture("junit/truncated.xml"),
        '<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="&a;"/></testsuite>',
        "<testsuitex/>",
        '<?xml version="1.0"?><report><testsuite name="x"/></report>',
    ],
)
def test_junit_rejects_missing_truncated_and_doctype_reports(text: str) -> None:
    assert parse_junit(text) is None


def test_junit_empty_report() -> None:
    assert _counts(parse_junit('<testsuite name="empty" tests="0"/>')) == (0, 0, 0, 0, 0)


def test_node_tap_nested_failure() -> None:
    run = parse_node_test(fixture("node/tap_fail.txt"))
    assert _counts(run) == (2, 1, 0, 1, 4)
    assert run is not None
    assert run["framework"] == "node-test"
    assert run["failing"] == ["Calculator > divides by zero"]
    assert run.get("cases") == [
        {"name": "Calculator > adds numbers", "outcome": "passed"},
        {"name": "Calculator > divides by zero", "outcome": "failed"},
        {"name": "Calculator > rounds", "outcome": "skipped"},
        {"name": "parses input", "outcome": "passed"},
    ]


def test_node_tap_inside_npm_with_todo() -> None:
    run = parse_node_test(fixture("node/tap_pass_npm.txt"))
    assert _counts(run) == (2, 0, 0, 1, 3)
    assert run is not None
    assert run["failing"] == []


def test_node_tap_cancelled_tests_are_errors() -> None:
    run = parse_node_test(fixture("node/tap_cancelled.txt"))
    assert _counts(run) == (0, 1, 1, 0, 2)
    assert run is not None
    assert run.get("cases") == [
        {"name": "fetches rows", "outcome": "failed"},
        {"name": "never starts", "outcome": "error"},
    ]


def test_node_tap_without_yaml_or_names() -> None:
    text = "TAP version 13\nnot ok 1\nok 2 - b\n1..2\n# tests 2\n# pass 1\n# fail 1\n"
    run = parse_node_test(text)
    assert _counts(run) == (1, 1, 0, 0, 2)
    assert run is not None
    assert run["failing"] == ["test 1"]


def test_node_spec_reporter() -> None:
    run = parse_node_test(fixture("node/spec_fail.txt"))
    assert _counts(run) == (2, 1, 0, 1, 4)
    assert run is not None
    assert run["failing"] == ["Calculator > divides by zero"]
    assert run.get("cases") == [
        {"name": "Calculator > adds numbers", "outcome": "passed"},
        {"name": "Calculator > divides by zero", "outcome": "failed"},
        {"name": "Calculator > rounds", "outcome": "skipped"},
        {"name": "parses input", "outcome": "passed"},
    ]


def test_node_spec_ansi_and_npm_todo() -> None:
    ansi = parse_node_test(fixture("node/spec_ansi.txt"))
    assert _counts(ansi) == (1, 1, 0, 0, 2)
    assert ansi is not None
    assert ansi["failing"] == ["divides by zero"]
    todo = parse_node_test(fixture("node/spec_pass_npm.txt"))
    assert _counts(todo) == (2, 0, 0, 1, 3)
    assert todo is not None
    assert [c["outcome"] for c in todo.get("cases", [])] == ["passed", "passed", "skipped"]


def test_node_spec_failing_section_fallback() -> None:
    text = (
        "\N{INFORMATION SOURCE} tests 1\n\N{INFORMATION SOURCE} pass 0\n"
        "\N{INFORMATION SOURCE} fail 1\n\n"
        "✖ failing tests:\n\ntest at t.js:1:1\n✖ boom (1.2ms)\n  Error: x\n"
    )
    run = parse_node_test(text)
    assert run is not None
    assert run["failing"] == ["boom"]


def test_node_not_recognized() -> None:
    assert parse_node_test("") is None
    assert parse_node_test("# tests 3\n") is None


def test_jest_default_reporter_inside_npm() -> None:
    run = parse_jest(fixture("jest/fail_npm.txt"))
    assert _counts(run) == (4, 1, 0, 1, 6)
    assert run is not None
    assert run["framework"] == "jest"
    assert run["failing"] == ["Calculator > divides by zero"]
    assert "cases" not in run


def test_jest_verbose_trees() -> None:
    passing = parse_jest(fixture("jest/verbose_pass.txt"))
    assert _counts(passing) == (3, 0, 0, 2, 5)
    assert passing is not None
    assert passing.get("cases") == [
        {"name": "Calculator > adds numbers", "outcome": "passed"},
        {"name": "Calculator > subtracts", "outcome": "passed"},
        {"name": "Calculator > nested > multiplies", "outcome": "passed"},
        {"name": "Calculator > rounds", "outcome": "skipped"},
        {"name": "Calculator > handles overflow", "outcome": "skipped"},
    ]
    failing = parse_jest(fixture("jest/verbose_fail.txt"))
    assert _counts(failing) == (1, 1, 0, 0, 2)
    assert failing is not None
    assert failing["failing"] == ["Calculator > divides by zero"]
    assert [c["outcome"] for c in failing.get("cases", [])] == ["passed", "failed"]


def test_jest_suite_that_fails_to_run() -> None:
    run = parse_jest(fixture("jest/suite_failed.txt"))
    assert _counts(run) == (0, 0, 1, 0, 1)
    assert run is not None
    assert run["failing"] == ["src/broken.test.js"]
    assert run["collection_error"] is True


def test_jest_ignores_warning_bullets_and_not_recognized() -> None:
    text = "  ● Validation Warning:\n\nTests:       2 passed, 2 total\n"
    run = parse_jest(text)
    assert run is not None
    assert run["failing"] == []
    assert parse_jest("Tests: none\n") is None


def test_vitest_failure_inside_npm() -> None:
    run = parse_vitest(fixture("vitest/fail_npm.txt"))
    assert _counts(run) == (4, 1, 0, 0, 5)
    assert run is not None
    assert run["framework"] == "vitest"
    assert run["failing"] == ["src/calc.test.ts > Calculator > divides by zero"]


def test_vitest_pass_with_skips() -> None:
    run = parse_vitest(fixture("vitest/pass.txt"))
    assert _counts(run) == (5, 0, 0, 1, 6)


def test_vitest_file_that_fails_to_load() -> None:
    run = parse_vitest(fixture("vitest/failed_suite.txt"))
    assert _counts(run) == (0, 0, 1, 0, 1)
    assert run is not None
    assert run["failing"] == ["src/broken.test.ts"]
    assert run["collection_error"] is True


def test_vitest_unhandled_errors_count_as_errors() -> None:
    run = parse_vitest(fixture("vitest/unhandled_error.txt"))
    assert _counts(run) == (2, 0, 1, 0, 3)


def test_vitest_not_recognized() -> None:
    assert parse_vitest("") is None
    assert parse_vitest("      Tests  are great\n") is None


def test_mocha_spec_reporter_inside_npm() -> None:
    run = parse_mocha(fixture("mocha/fail_npm.txt"))
    assert _counts(run) == (3, 1, 0, 1, 5)
    assert run is not None
    assert run["framework"] == "mocha"
    assert run["failing"] == ["Calculator > divides by zero"]
    assert run.get("cases") == [
        {"name": "Calculator > adds numbers", "outcome": "passed"},
        {"name": "Calculator > divides by zero", "outcome": "failed"},
        {"name": "Calculator > rounds", "outcome": "skipped"},
        {"name": "Calculator > nested > multiplies", "outcome": "passed"},
        {"name": "parse > parses input", "outcome": "passed"},
    ]


def test_mocha_hooks_and_top_level_failures() -> None:
    run = parse_mocha(fixture("mocha/hook_fail.txt"))
    assert _counts(run) == (1, 2, 0, 0, 3)
    assert run is not None
    assert run["failing"] == ['db > "before all" hook for "reads rows"', "top level fails"]


def test_mocha_pass_and_fallback_names() -> None:
    assert _counts(parse_mocha(fixture("mocha/pass.txt"))) == (2, 0, 0, 0, 2)
    text = "  suite\n    1) breaks\n\n  0 passing (1ms)\n  1 failing\n"
    run = parse_mocha(text)
    assert run is not None
    assert run["failing"] == ["suite > breaks"]
    assert parse_mocha("1 failing\n") is None
