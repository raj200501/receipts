"""Tests for the pytest and unittest parsers (hand-written fixtures under tests/fixtures/ledger)."""

from __future__ import annotations

import pytest

from receipts.ledger.parsers.python_tests import (
    merge_cases,
    parse_pytest,
    parse_unittest,
    split_nodeid,
)

from .helpers import fixture

# fixture, passed, failed, errors, skipped, failing, collection_error
PYTEST_CASES = [
    ("pytest/pass_normal.txt", 12, 0, 0, 0, [], False),
    (
        "pytest/fail_normal.txt",
        10,
        2,
        0,
        1,
        ["tests/test_calc.py::test_div", "tests/test_parse.py::test_parse[a - b]"],
        False,
    ),
    (
        "pytest/errors_normal.txt",
        3,
        1,
        2,
        0,
        [
            "tests/test_api.py::test_status",
            "tests/test_db.py::test_connect",
            "tests/test_db.py::test_query",
        ],
        False,
    ),
    ("pytest/quiet_fail.txt", 5, 1, 0, 1, ["tests/test_io.py::test_roundtrip"], False),
    ("pytest/quiet_pass.txt", 8, 0, 0, 0, [], False),
    ("pytest/ra_mode.txt", 4, 0, 0, 2, [], False),
    ("pytest/verbose.txt", 2, 1, 0, 1, ["tests/test_slug.py::test_unicode"], False),
    ("pytest/collection_error.txt", 0, 0, 1, 0, ["tests/test_cart.py"], True),
    ("pytest/no_tests.txt", 0, 0, 0, 0, [], False),
    ("pytest/ansi.txt", 4, 1, 0, 0, ["tests/test_calc.py::test_neg"], False),
    ("pytest/make_wrapper.txt", 3, 1, 0, 0, ["tests/test_cli.py::test_help"], False),
    ("pytest/xdist_long.txt", 2, 1, 0, 0, ["tests/test_load.py::test_load_json"], False),
]


@pytest.mark.parametrize(
    ("name", "passed", "failed", "errors", "skipped", "failing", "collection"), PYTEST_CASES
)
def test_pytest_fixture_corpus(
    name: str,
    passed: int,
    failed: int,
    errors: int,
    skipped: int,
    failing: list[str],
    collection: bool,
) -> None:
    run = parse_pytest(fixture(name))
    assert run is not None
    assert run["framework"] == "pytest"
    assert (run["passed"], run["failed"], run["errors"], run["skipped"]) == (
        passed,
        failed,
        errors,
        skipped,
    )
    assert run["total"] == passed + failed + errors + skipped
    assert run["failing"] == failing
    assert run["collection_error"] is collection


def test_pytest_truncated_or_unrelated_output_is_not_recognized() -> None:
    assert parse_pytest(fixture("pytest/truncated.txt")) is None
    assert parse_pytest("") is None
    assert parse_pytest("=== FAILURES ===\nfoo in 0.1s\n  3 passed in 0.1s\n") is None
    assert parse_pytest("=== 3 bananas in 0.1s ===") is None


def test_pytest_ra_mode_cases_map_xfail_and_xpass() -> None:
    run = parse_pytest(fixture("pytest/ra_mode.txt"))
    assert run is not None
    assert run["cases"] == [
        {"name": "tests/test_flags.py::test_on", "outcome": "passed"},
        {"name": "tests/test_flags.py::test_off", "outcome": "passed"},
        {"name": "tests/test_flags.py::test_toggle[True]", "outcome": "passed"},
        {"name": "tests/test_flags.py::test_legacy", "outcome": "skipped"},
        {"name": "tests/test_flags.py::test_maybe", "outcome": "passed"},
    ]


def test_pytest_verbose_cases_include_skips_and_bracketed_ids() -> None:
    run = parse_pytest(fixture("pytest/verbose.txt"))
    assert run is not None
    assert run["cases"] == [
        {"name": "tests/test_slug.py::test_basic", "outcome": "passed"},
        {"name": "tests/test_slug.py::test_unicode", "outcome": "failed"},
        {"name": "tests/test_slug.py::test_long[a b]", "outcome": "passed"},
        {"name": "tests/test_slug.py::test_windows", "outcome": "skipped"},
    ]


def test_pytest_without_case_lines_has_no_cases_key() -> None:
    run = parse_pytest(fixture("pytest/pass_normal.txt"))
    assert run is not None
    assert "cases" not in run


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1 passed in 1.00 seconds", (1, 0, 0, 0)),
        ("=== 2 passed, 3 deselected in 0.01s ===", (2, 0, 0, 0)),
        ("=== 3 deselected in 0.01s ===", (0, 0, 0, 0)),
        ("no tests ran in 0.01s", (0, 0, 0, 0)),
        ("=== 1 failed, 1 passed, 2 rerun in 0.30s ===", (1, 1, 0, 0)),
        ("=== 1 passed, 1 warning, 1 error in 0.12s ===", (1, 0, 1, 0)),
        ("=== 1 xfailed, 1 xpassed in 0.12s ===", (1, 0, 0, 1)),
        ("========= 3 passed in 65.43s (0:01:05) =========", (3, 0, 0, 0)),
    ],
)
def test_pytest_summary_line_variants(line: str, expected: tuple[int, int, int, int]) -> None:
    run = parse_pytest(line + "\n")
    assert run is not None
    assert (run["passed"], run["failed"], run["errors"], run["skipped"]) == expected


def test_pytest_sessions_in_one_output_are_added() -> None:
    text = fixture("pytest/quiet_fail.txt") + "\n" + fixture("pytest/pass_normal.txt")
    run = parse_pytest(text)
    assert run is not None
    assert (run["passed"], run["failed"], run["skipped"], run["total"]) == (17, 1, 1, 19)


def test_pytest_summary_lines_without_header_need_plausible_ids() -> None:
    text = "FAILED tests/test_a.py::test_x - boom\nFAILED garbage here\n1 failed in 0.1s\n"
    run = parse_pytest(text)
    assert run is not None
    assert run["failing"] == ["tests/test_a.py::test_x"]


def test_pytest_failing_falls_back_to_section_headers() -> None:
    text = (
        "=================================== FAILURES ===================================\n"
        "___________________________ TestCalc.test_div ____________________________\n"
        "E   ZeroDivisionError\n"
        "==================================== ERRORS ====================================\n"
        "_____________________ ERROR at teardown of test_conn ______________________\n"
        "==================== 1 failed, 1 passed, 1 error in 0.1s ====================\n"
    )
    run = parse_pytest(text)
    assert run is not None
    assert run["failing"] == ["TestCalc.test_div", "test_conn"]


def test_pytest_continue_on_collection_errors_is_not_a_collection_abort() -> None:
    text = (
        "_____________________ ERROR collecting tests/test_cart.py ______________________\n"
        "=========================== short test summary info ============================\n"
        "ERROR tests/test_cart.py\n"
        "==================== 2 passed, 1 error in 0.10s ====================\n"
    )
    run = parse_pytest(text)
    assert run is not None
    assert run["collection_error"] is False
    assert run["failing"] == ["tests/test_cart.py"]


def test_pytest_captured_log_lines_are_not_failures() -> None:
    run = parse_pytest(fixture("pytest/errors_normal.txt"))
    assert run is not None
    assert all("shop.api" not in name for name in run["failing"])


def test_split_nodeid_respects_brackets() -> None:
    assert split_nodeid("tests/a.py::t[a - b] - AssertionError") == "tests/a.py::t[a - b]"
    assert split_nodeid("tests/a.py::t - boom") == "tests/a.py::t"
    assert split_nodeid("tests/a.py") == "tests/a.py"
    assert split_nodeid("t[x]] y") == "t[x]]"


def test_merge_cases_keeps_the_most_severe_outcome() -> None:
    merged = merge_cases(
        [("a", "passed"), ("b", "skipped"), ("a", "error"), ("a", "failed"), ("b", "passed")]
    )
    assert merged == [{"name": "a", "outcome": "error"}, {"name": "b", "outcome": "passed"}]


def test_unittest_failures_and_errors() -> None:
    run = parse_unittest(fixture("unittest/fail.txt"))
    assert run is not None
    assert run["framework"] == "unittest"
    assert (run["passed"], run["failed"], run["errors"], run["skipped"], run["total"]) == (
        3,
        1,
        1,
        1,
        6,
    )
    assert run["failing"] == [
        "tests.test_db.DbTest.test_connect",
        "tests.test_calc.CalcTest.test_div",
    ]
    assert run["collection_error"] is False


def test_unittest_verbose_old_naming_and_expected_failures() -> None:
    run = parse_unittest(fixture("unittest/pass.txt"))
    assert run is not None
    assert (run["passed"], run["skipped"], run["total"]) == (2, 1, 3)
    assert run["cases"] == [
        {"name": "tests.test_calc.CalcTest.test_add", "outcome": "passed"},
        {"name": "tests.test_calc.CalcTest.test_legacy", "outcome": "skipped"},
        {"name": "tests.test_calc.CalcTest.test_sub", "outcome": "passed"},
    ]


def test_unittest_import_failure_is_a_collection_error() -> None:
    run = parse_unittest(fixture("unittest/import_error.txt"))
    assert run is not None
    assert run["errors"] == 1
    assert run["failing"] == ["tests.test_cart"]
    assert run["collection_error"] is True


def test_unittest_other_results() -> None:
    text = (
        "test_a (t.T.test_a) ... skipped 'later'\n"
        "test_b (t.T.test_b) ... unexpected success\n"
        "test_c (t.T.test_c) ... FAIL\n"
        "test_d (t.T.test_d) ... ERROR\n"
        "Ran 4 tests in 0.01s\n\nFAILED (failures=1, errors=1, skipped=1, unexpected successes=1)\n"
    )
    run = parse_unittest(text)
    assert run is not None
    assert (run["passed"], run["failed"], run["errors"], run["skipped"]) == (0, 2, 1, 1)
    assert [case["outcome"] for case in run.get("cases", [])] == [
        "skipped",
        "failed",
        "failed",
        "error",
    ]


def test_unittest_not_recognized() -> None:
    assert parse_unittest("") is None
    assert parse_unittest("Ran 3 tests in 0.1s\n") is None
    assert parse_unittest("Ran 3 tests in 0.1s\n\nmaybe\n") is None
    run = parse_unittest("Ran 0 tests in 0.000s\n\nNO TESTS RAN\n")
    assert run is not None and run["total"] == 0
