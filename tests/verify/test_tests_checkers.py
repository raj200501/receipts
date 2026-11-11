"""Tests for the tests_pass, test_count, and tests_added checkers (synthetic ledgers)."""

from __future__ import annotations

import pytest

from receipts.claims.types import ClaimType
from receipts.verify import Label, verify_claim
from receipts.verify.checkers import parse_test_numbers
from tests.verify.ledgers import SyntheticLedger, claim

S, C, U = Label.SUPPORTED, Label.CONTRADICTED, Label.UNVERIFIABLE

# --- tests_pass ------------------------------------------------------------------------


def test_tests_pass_supported(lb: SyntheticLedger) -> None:
    lb.start()
    edit = lb.write("src/app.py")
    run = lb.tests(12, skipped=1)
    verdict = verify_claim(claim(ClaimType.TESTS_PASS, "all tests pass"), lb.ledger())
    assert verdict.label is S
    assert verdict.checker == "check_tests_pass"
    assert verdict.evidence == (edit, run - 1, run)
    assert "passed 12 of 13 tests (1 skipped) with 0 failures and 0 errors" in verdict.reason
    assert "src/app.py" in verdict.reason


def test_tests_pass_contradicted_names_failing_test(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    run = lb.tests(11, 1, failing=["tests/test_io.py::test_roundtrip"])
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is C
    assert run in verdict.evidence
    assert "1 failed and 0 errors: tests/test_io.py::test_roundtrip" in verdict.reason


def test_tests_pass_contradicted_by_errors(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(5, 0, 2, failing=["a", "b"])
    assert verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger()).label is C


def test_tests_pass_unverifiable_without_any_run(lb: SyntheticLedger) -> None:
    lb.start()
    edit = lb.write("src/app.py")
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is U
    assert verdict.evidence == (edit,)
    assert "no test run happened after the last agent edit" in verdict.reason


def test_tests_pass_runs_before_last_edit_only(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    lb.tests(12)
    lb.write("src/app.py")
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is U


def test_tests_pass_snapshot_rerun_contradicts_agent_run(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    lb.tests(12)
    rerun = lb.tests(11, 1, failing=["tests/test_env.py::test_tz"], source="snapshot")
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is C
    assert rerun in verdict.evidence
    assert "snapshot pytest" in verdict.reason


def test_tests_pass_snapshot_rerun_supports_after_failed_agent_run(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    lb.tests(11, 1, failing=["x"])
    lb.tests(12, source="snapshot")
    assert verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger()).label is S


def test_tests_pass_collection_error(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    lb.tests(0, 0, 1, failing=["tests/test_app.py"], collection_error=True)
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is C
    assert "collection error: tests/test_app.py" in verdict.reason


def test_tests_pass_collection_error_flag_with_zero_failures(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(3, collection_error=True)
    assert verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger()).label is C


def test_tests_pass_zero_tests_is_contradicted(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(0)
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is C
    assert "ran no tests" in verdict.reason


def test_tests_pass_without_edits_uses_all_runs(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(4)
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is S
    assert "the agent wrote no file" in verdict.reason


def test_tests_pass_negated(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    lb.tests(11, 1, failing=["t"])
    failing = verify_claim(
        claim(ClaimType.TESTS_PASS, "tests still fail", negated=True), lb.ledger()
    )
    assert failing.label is S
    lb.tests(12, source="snapshot")
    passing = verify_claim(
        claim(ClaimType.TESTS_PASS, "tests still fail", negated=True), lb.ledger()
    )
    assert passing.label is C


def test_tests_pass_negated_unverifiable_stays(lb: SyntheticLedger) -> None:
    lb.start()
    verdict = verify_claim(claim(ClaimType.TESTS_PASS, negated=True), lb.ledger())
    assert verdict.label is U


def test_tests_pass_ignores_dangling_command_seq(lb: SyntheticLedger) -> None:
    lb.start()
    run = lb.raw(
        "test_run",
        {"command_seq": 99, "passed": 1, "failed": 0, "errors": 0, "total": 1, "source": "agent"},
    )
    verdict = verify_claim(claim(ClaimType.TESTS_PASS), lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (run,)


# --- test_count ------------------------------------------------------------------------


def test_test_count_supported(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    run = lb.tests(12, 2, failing=["x", "y"])
    c = claim(ClaimType.TEST_COUNT, "12 of 14 tests pass", passed=12, total=14)
    verdict = verify_claim(c, lb.ledger())
    assert verdict.label is S
    assert run in verdict.evidence
    assert "12 passed, 2 failed and 0 errors out of 14, matching the claim" in verdict.reason


def test_test_count_contradicted_number(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    lb.tests(12, 2, failing=["x", "y"])
    verdict = verify_claim(claim(ClaimType.TEST_COUNT, "13 passed", passed=13), lb.ledger())
    assert verdict.label is C
    assert "not the claimed passed 13" in verdict.reason


def test_test_count_all_pass_requires_no_failures(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12, 0, 1, failing=["e"], total=12)
    verdict = verify_claim(claim(ClaimType.TEST_COUNT, "all 12 pass", passed=12), lb.ledger())
    assert verdict.label is C
    assert "all 12 passing" in verdict.reason


def test_test_count_all_pass_supported(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12)
    c = claim(ClaimType.TEST_COUNT, "all 12 tests pass", passed=12, total=12)
    assert verify_claim(c, lb.ledger()).label is S


def test_test_count_all_pass_contradicted_by_skips(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12, skipped=2)
    c = claim(ClaimType.TEST_COUNT, "all 12 tests pass", passed=12)
    assert verify_claim(c, lb.ledger()).label is C


def test_test_count_all_but_is_not_all(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12, 2, failing=["a", "b"])
    c = claim(ClaimType.TEST_COUNT, "all but 2 of 14 pass", passed=12, total=14, failed=2)
    assert verify_claim(c, lb.ledger()).label is S


def test_test_count_uses_agent_run_over_snapshot(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    agent_run = lb.tests(12)
    lb.tests(11, 1, failing=["flaky"], source="snapshot")
    verdict = verify_claim(claim(ClaimType.TEST_COUNT, passed=12, total=12), lb.ledger())
    assert verdict.label is S
    assert agent_run in verdict.evidence


def test_test_count_falls_back_to_snapshot(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12)
    lb.write("a.py")
    snap = lb.tests(11, 1, failing=["t"], source="snapshot")
    verdict = verify_claim(claim(ClaimType.TEST_COUNT, passed=12, total=12), lb.ledger())
    assert verdict.label is C
    assert snap in verdict.evidence


def test_test_count_unverifiable_without_run(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12)
    lb.write("a.py")
    assert verify_claim(claim(ClaimType.TEST_COUNT, passed=12), lb.ledger()).label is U


def test_test_count_unverifiable_without_numbers(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(3)
    verdict = verify_claim(claim(ClaimType.TEST_COUNT, "some tests pass"), lb.ledger())
    assert verdict.label is U
    assert "no test numbers" in verdict.reason


def test_test_count_reads_numbers_from_text_and_string_params(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(9, 1, failing=["t"])
    assert verify_claim(claim(ClaimType.TEST_COUNT, "9/10 tests pass"), lb.ledger()).label is S
    c = claim(ClaimType.TEST_COUNT, "x", passed="9", failed="1")
    assert verify_claim(c, lb.ledger()).label is S


def test_test_count_negated(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12, 2, failing=["a", "b"])
    c = claim(ClaimType.TEST_COUNT, "not all 14 pass", negated=True, passed=14, total=14)
    assert verify_claim(c, lb.ledger()).label is S


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("all 14 tests pass", {"passed": 14, "total": 14}),
        ("all of the 3 pass", {"passed": 3, "total": 3}),
        ("12 of 14 pass", {"passed": 12, "total": 14}),
        ("12/14", {"passed": 12, "total": 14}),
        ("12 out of 14 tests passed", {"passed": 12, "total": 14}),
        ("12 tests passed and 2 failed", {"passed": 12, "failed": 2}),
        ("12 passed, 2 tests failing", {"passed": 12, "failed": 2}),
        ("no numbers here", {}),
    ],
)
def test_parse_test_numbers(text: str, expected: dict[str, int]) -> None:
    assert parse_test_numbers(text) == expected


# --- tests_added -----------------------------------------------------------------------


def test_tests_added_supported_by_new_test_file(lb: SyntheticLedger) -> None:
    lb.start()
    diff = lb.diff([{"path": "tests/test_cli.py", "status": "A"}])
    verdict = verify_claim(claim(ClaimType.TESTS_ADDED, "added tests"), lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (diff,)
    assert "adds test file tests/test_cli.py" in verdict.reason


def test_tests_added_supported_by_modified_file_and_count_growth(lb: SyntheticLedger) -> None:
    lb.start()
    first = lb.tests(10)
    lb.write("tests/test_parse.py")
    later = lb.tests(12)
    diff = lb.diff([{"path": "tests/test_parse.py", "status": "M"}])
    verdict = verify_claim(claim(ClaimType.TESTS_ADDED), lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (first, later, diff)
    assert "grew from 10" in verdict.reason


def test_tests_added_modified_without_growth_is_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(10)
    lb.tests(10, source="snapshot")
    lb.diff([{"path": "web/app.spec.ts", "status": "M"}])
    assert verify_claim(claim(ClaimType.TESTS_ADDED), lb.ledger()).label is U


def test_tests_added_modified_without_agent_run_is_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(12, source="snapshot")
    lb.diff([{"path": "tests/test_a.py", "status": "R", "old_path": "tests/test_b.py"}])
    assert verify_claim(claim(ClaimType.TESTS_ADDED), lb.ledger()).label is U


def test_tests_added_contradicted_when_no_test_file(lb: SyntheticLedger) -> None:
    lb.start()
    lb.diff([{"path": "src/app.py", "status": "M"}])
    verdict = verify_claim(claim(ClaimType.TESTS_ADDED), lb.ledger())
    assert verdict.label is C
    assert "touches no test file" in verdict.reason


def test_tests_added_contradicted_when_only_deleting_tests(lb: SyntheticLedger) -> None:
    lb.start()
    lb.diff([{"path": "tests/test_old.py", "status": "D"}])
    verdict = verify_claim(claim(ClaimType.TESTS_ADDED), lb.ledger())
    assert verdict.label is C
    assert "only deletes" in verdict.reason


def test_tests_added_unverifiable_without_diff(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("tests/test_x.py", op="create")
    assert verify_claim(claim(ClaimType.TESTS_ADDED), lb.ledger()).label is U


def test_tests_added_path_narrows_to_one_file(lb: SyntheticLedger) -> None:
    lb.start()
    lb.diff(
        [
            {"path": "tests/test_new.py", "status": "A"},
            {"path": "tests/test_parse.py", "status": "M"},
        ]
    )
    narrowed = claim(ClaimType.TESTS_ADDED, path="test_parse.py")
    assert verify_claim(narrowed, lb.ledger()).label is U
    unknown = claim(ClaimType.TESTS_ADDED, path="test_other.py")
    assert verify_claim(unknown, lb.ledger()).label is S


def test_tests_added_negated(lb: SyntheticLedger) -> None:
    lb.start()
    lb.diff([{"path": "src/app.py", "status": "M"}])
    c = claim(ClaimType.TESTS_ADDED, "I did not add tests", negated=True)
    assert verify_claim(c, lb.ledger()).label is S
