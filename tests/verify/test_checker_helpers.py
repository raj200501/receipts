"""Direct tests for the checker helpers and registry (synthetic claims and ledgers)."""

from __future__ import annotations

from receipts.claims.types import ClaimType
from receipts.verify import CHECKERS, Finding, Label, LedgerFacts
from receipts.verify.checkers import check_tests_pass, name_list, param_int, param_str
from tests.verify.ledgers import SyntheticLedger, claim


def test_checker_names_follow_claim_types() -> None:
    for kind, checker in CHECKERS.items():
        assert checker.__name__ == f"check_{kind.value}"
        assert checker.__doc__


def test_param_str() -> None:
    c = claim(ClaimType.RAN_COMMAND, command="  pytest  ", blank="   ", number=3)
    assert param_str(c, "command") == "pytest"
    assert param_str(c, "blank") is None
    assert param_str(c, "missing") is None
    assert param_str(c, "number") == "3"


def test_param_int() -> None:
    c = claim(ClaimType.TEST_COUNT, passed=4, total=" 12 ", failed="two", skipped=None)
    assert param_int(c, "passed") == 4
    assert param_int(c, "total") == 12
    assert param_int(c, "failed") is None
    assert param_int(c, "skipped") is None


def test_name_list() -> None:
    assert name_list(["a", "b"]) == "a, b"
    assert name_list(["a", "", "b", "c"], limit=2) == "a, b and 1 more"
    assert name_list([]) == "(names not recorded)"
    assert name_list([""]) == "(names not recorded)"


def test_checkers_can_be_called_directly_without_negation(lb: SyntheticLedger) -> None:
    lb.start()
    lb.tests(2, 1, failing=["t"])
    facts = LedgerFacts(lb.ledger())
    finding = check_tests_pass(claim(ClaimType.TESTS_PASS, negated=True), facts, None)
    assert isinstance(finding, Finding)
    assert finding.label is Label.CONTRADICTED  # the positive reading; negation is applied later
