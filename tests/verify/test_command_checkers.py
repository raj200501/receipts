"""Tests for ran_command, lint_clean, typecheck_clean, and build_succeeds (synthetic ledgers)."""

from __future__ import annotations

from receipts.claims.types import ClaimType
from receipts.verify import Label, verify_claim
from tests.verify.ledgers import SyntheticLedger, claim

S, C, U = Label.SUPPORTED, Label.CONTRADICTED, Label.UNVERIFIABLE

# --- ran_command -----------------------------------------------------------------------


def test_ran_command_supported_after_normalization(lb: SyntheticLedger) -> None:
    lb.start()
    seq = lb.command("uv run --no-sync python -m pytest -q tests/")
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="`pytest`"), lb.ledger())
    assert verdict.label is S
    assert verdict.checker == "check_ran_command"
    assert verdict.evidence == (seq,)
    assert f"(event {seq})" in verdict.reason
    assert "uv run --no-sync python -m pytest -q tests/" in verdict.reason


def test_ran_command_counts_failed_commands_as_run(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("npm test", exit_code=1)
    c = claim(ClaimType.RAN_COMMAND, command="npm run test")
    assert verify_claim(c, lb.ledger()).label is S


def test_ran_command_contradicted(lb: SyntheticLedger) -> None:
    lb.start()
    seq = lb.command("ruff check .")
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="pytest -q"), lb.ledger())
    assert verdict.label is C
    assert verdict.evidence == (seq,)
    assert "none of the 1 agent commands in the ledger matches 'pytest -q'" in verdict.reason


def test_ran_command_ignores_pipe_filters_in_claim(lb: SyntheticLedger) -> None:
    lb.start()
    seq = lb.command("pytest -q 2>&1")
    c = claim(ClaimType.RAN_COMMAND, command="pytest -q 2>&1 | tail -20")
    verdict = verify_claim(c, lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (seq,)


def test_ran_command_ignores_snapshot_commands(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("pytest -q", source="snapshot")
    assert verify_claim(claim(ClaimType.RAN_COMMAND, command="pytest"), lb.ledger()).label is C


def test_ran_command_claimed_flags_must_be_recorded(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("pytest")
    c = claim(ClaimType.RAN_COMMAND, command="pytest --cov")
    assert verify_claim(c, lb.ledger()).label is C


def test_ran_command_compound_claim_across_commands(lb: SyntheticLedger) -> None:
    lb.start()
    first = lb.command("ruff check .")
    second = lb.command("mypy --strict src")
    c = claim(ClaimType.RAN_COMMAND, command="ruff check . && mypy src")
    verdict = verify_claim(c, lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (first, second)


def test_ran_command_compound_claim_partly_missing(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("ruff check .")
    c = claim(ClaimType.RAN_COMMAND, command="ruff check . && mypy src")
    assert verify_claim(c, lb.ledger()).label is C


def test_ran_command_generic_tests_via_test_run(lb: SyntheticLedger) -> None:
    lb.start()
    run = lb.tests(3, cmd="python -m unittest")
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="the tests"), lb.ledger())
    assert verdict.label is S
    assert run in verdict.evidence
    assert "the agent ran the tests" in verdict.reason


def test_ran_command_generic_tests_via_unparsed_command(lb: SyntheticLedger) -> None:
    lb.start()
    seq = lb.command("go test ./...")
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="the test suite"), lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (seq,)


def test_ran_command_generic_tests_contradicted(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("ls")
    lb.tests(3, source="snapshot")
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="the tests"), lb.ledger())
    assert verdict.label is C
    assert "no agent command in the ledger ran the tests" in verdict.reason


def test_ran_command_generic_linter(lb: SyntheticLedger) -> None:
    lb.start()
    lb.lint(0)
    assert verify_claim(claim(ClaimType.RAN_COMMAND, command="the linter"), lb.ledger()).label is S


def test_ran_command_generic_type_checker_and_build(lb: SyntheticLedger) -> None:
    lb.start()
    lb.typecheck(2)
    lb.command("npm run build")
    ledger = lb.ledger()
    tc = claim(ClaimType.RAN_COMMAND, command="the type checker")
    assert verify_claim(tc, ledger).label is S
    assert verify_claim(claim(ClaimType.RAN_COMMAND, command="the build"), ledger).label is S


def test_ran_command_negated(lb: SyntheticLedger) -> None:
    lb.start()
    lb.lint(0)
    did_not_lint = claim(
        ClaimType.RAN_COMMAND, "I did not run the linter", negated=True, command="the linter"
    )
    assert verify_claim(did_not_lint, lb.ledger()).label is C
    did_not_test = claim(ClaimType.RAN_COMMAND, negated=True, command="pytest")
    assert verify_claim(did_not_test, lb.ledger()).label is S


def test_ran_command_without_command_param(lb: SyntheticLedger) -> None:
    lb.start()
    assert verify_claim(claim(ClaimType.RAN_COMMAND), lb.ledger()).label is U


def test_ran_command_empty_after_normalization(lb: SyntheticLedger) -> None:
    lb.start()
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="cd src"), lb.ledger())
    assert verdict.label is U
    assert "is empty" in verdict.reason


def test_ran_command_long_command_is_shortened_in_reason(lb: SyntheticLedger) -> None:
    lb.start()
    long_cmd = "pytest " + " ".join(f"tests/test_{i}.py" for i in range(40))
    lb.command(long_cmd)
    verdict = verify_claim(claim(ClaimType.RAN_COMMAND, command="pytest"), lb.ledger())
    assert verdict.label is S
    assert "...'" in verdict.reason


# --- lint_clean / typecheck_clean --------------------------------------------------------


def test_lint_clean_supported(lb: SyntheticLedger) -> None:
    lb.start()
    edit = lb.write("a.py")
    run = lb.lint(0)
    verdict = verify_claim(claim(ClaimType.LINT_CLEAN, "ruff is clean"), lb.ledger())
    assert verdict.label is S
    assert verdict.checker == "check_lint_clean"
    assert verdict.evidence == (edit, run - 1, run)
    assert "reported 0 errors" in verdict.reason


def test_lint_clean_contradicted(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    lb.lint(3)
    verdict = verify_claim(claim(ClaimType.LINT_CLEAN), lb.ledger())
    assert verdict.label is C
    assert "reported 3 errors" in verdict.reason


def test_lint_clean_unverifiable_when_lint_ran_before_last_edit(lb: SyntheticLedger) -> None:
    lb.start()
    lb.lint(0)
    lb.write("a.py")
    assert verify_claim(claim(ClaimType.LINT_CLEAN), lb.ledger()).label is U


def test_lint_clean_snapshot_run_counts(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    lb.lint(0)
    lb.lint(1, source="snapshot")
    assert verify_claim(claim(ClaimType.LINT_CLEAN), lb.ledger()).label is C


def test_lint_clean_tool_filter(lb: SyntheticLedger) -> None:
    lb.start()
    lb.lint(0, tool="ruff")
    lb.lint(4, tool="eslint")
    ledger = lb.ledger()
    assert verify_claim(claim(ClaimType.LINT_CLEAN, tool="ruff"), ledger).label is S
    assert verify_claim(claim(ClaimType.LINT_CLEAN, tool="ESLint"), ledger).label is C
    assert verify_claim(claim(ClaimType.LINT_CLEAN, tool="flake8"), ledger).label is C


def test_typecheck_clean(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    lb.typecheck(0)
    assert verify_claim(claim(ClaimType.TYPECHECK_CLEAN), lb.ledger()).label is S
    lb.typecheck(2, source="snapshot")
    verdict = verify_claim(claim(ClaimType.TYPECHECK_CLEAN, tool="mypy"), lb.ledger())
    assert verdict.label is C
    assert verdict.checker == "check_typecheck_clean"


def test_typecheck_clean_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    verdict = verify_claim(claim(ClaimType.TYPECHECK_CLEAN), lb.ledger())
    assert verdict.label is U
    assert "no type-check run" in verdict.reason


def test_typecheck_clean_negated(lb: SyntheticLedger) -> None:
    lb.start()
    lb.typecheck(5)
    c = claim(ClaimType.TYPECHECK_CLEAN, "mypy still reports errors", negated=True)
    assert verify_claim(c, lb.ledger()).label is S


# --- build_succeeds --------------------------------------------------------------------


def test_build_succeeds_supported(lb: SyntheticLedger) -> None:
    lb.start()
    edit = lb.write("web/app.ts")
    seq = lb.command("cd web && npm run build")
    verdict = verify_claim(claim(ClaimType.BUILD_SUCCEEDS), lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (edit, seq)
    assert "exited 0" in verdict.reason


def test_build_succeeds_contradicted_by_snapshot(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    lb.command("python -m build")
    lb.command("python -m build", exit_code=1, source="snapshot")
    verdict = verify_claim(claim(ClaimType.BUILD_SUCCEEDS), lb.ledger())
    assert verdict.label is C
    assert "exited 1" in verdict.reason


def test_build_succeeds_timeout_is_contradicted(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("make build", timed_out=True)
    verdict = verify_claim(claim(ClaimType.BUILD_SUCCEEDS), lb.ledger())
    assert verdict.label is C
    assert "timed out" in verdict.reason


def test_build_succeeds_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("tsc")
    lb.write("a.ts")
    lb.command("ls")
    lb.command("tsc", source="harness")
    assert verify_claim(claim(ClaimType.BUILD_SUCCEEDS), lb.ledger()).label is U


def test_build_succeeds_tool_filter(lb: SyntheticLedger) -> None:
    lb.start()
    lb.command("tsc -p .", exit_code=2)
    lb.command("npm run build")
    ledger = lb.ledger()
    assert verify_claim(claim(ClaimType.BUILD_SUCCEEDS, tool="tsc"), ledger).label is C
    assert verify_claim(claim(ClaimType.BUILD_SUCCEEDS, tool="webpack"), ledger).label is S
