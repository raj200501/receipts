"""Tests for receipts.verify.facts (all ledgers are synthetic)."""

from __future__ import annotations

import pytest

from receipts.ledger.events import Ledger
from receipts.verify.facts import CheckResult, LedgerFacts, as_int, as_list, as_str, evidence_of
from tests.verify.ledgers import SyntheticLedger


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3), (True, 1), (2.9, 2), (" 7 ", 7), ("-2", -2), ("x", 0), (None, 0), ([1], 0)],
)
def test_as_int(value: object, expected: int) -> None:
    assert as_int(value) == expected


def test_as_int_default() -> None:
    assert as_int("nope", -1) == -1


def test_as_str_and_as_list() -> None:
    assert as_str(None) == ""
    assert as_str(5) == "5"
    assert as_list([1, 2]) == [1, 2]
    assert as_list((1,)) == [1]
    assert as_list("ab") == []


def test_evidence_of_merges_sorts_and_drops_negatives() -> None:
    assert evidence_of(5, [3, 5, -1], None, (2,), -1) == (2, 3, 5)
    assert evidence_of() == ()


def test_empty_ledger_facts() -> None:
    facts = LedgerFacts(Ledger([]))
    assert facts.last_edit == -1
    assert facts.diff is None
    assert facts.checks == ()
    assert facts.conditions == {}
    assert not facts.unattainable
    assert facts.ground_truth_success() is None
    assert facts.diff_files() == []
    assert facts.dependency_changes() == []
    assert facts.edit_phrase() == "the start of the run (the agent wrote no file)"
    assert facts.command_text(0) == ""


def test_last_edit_is_last_agent_write_only(lb: SyntheticLedger) -> None:
    lb.start()
    first = lb.write("a.py")
    run = lb.tests(3)
    lb.write("gen.py", source="snapshot")
    facts = LedgerFacts(lb.ledger())
    assert facts.last_edit == first
    assert facts.edit_phrase() == f"the last agent edit (a.py, event {first})"
    assert [e.seq for e in facts.after_edit("test_run")] == [run]
    assert facts.last_after_edit("test_run", source="snapshot") is None
    assert facts.last_after_edit("test_run", source="agent") is not None
    assert [e.seq for e in facts.agent_writes] == [first]


def test_command_text_only_for_command_events(lb: SyntheticLedger) -> None:
    lb.start()
    cmd = lb.command("ls")
    facts = LedgerFacts(lb.ledger())
    assert facts.command_text(cmd) == "ls"
    assert facts.command_text(0) == ""
    assert facts.command_text("x") == ""
    assert [e.seq for e in facts.agent_commands()] == [cmd]


def test_conditions_and_unattainable(lb: SyntheticLedger) -> None:
    lb.start({"M1": " Unattainable ", "M2": "truncated"})
    facts = LedgerFacts(lb.ledger())
    assert facts.unattainable
    assert facts.conditions["M2"] == "truncated"


def test_non_mapping_conditions_are_ignored(lb: SyntheticLedger) -> None:
    lb.raw("run_start", {"conditions": ["M1"], "source": "harness"})
    assert LedgerFacts(lb.ledger()).conditions == {}


def test_hidden_checks_flatten_and_later_wins(lb: SyntheticLedger) -> None:
    first = lb.hidden([("a", False, "R1"), ("b", True, None)])
    second = lb.hidden([("a", True, "R1")])
    lb.raw("hidden_check", {"checks": ["junk", {"name": "c", "passed": "yes"}], "total": 1})
    facts = LedgerFacts(lb.ledger())
    assert facts.checks[0] == CheckResult("a", True, "R1", second)
    assert facts.checks[1] == CheckResult("b", True, None, first)
    assert facts.checks[2].passed is False  # only the JSON value true counts as passed
    assert facts.ground_truth_success() is False


def test_ground_truth_from_counts_when_no_check_list(lb: SyntheticLedger) -> None:
    lb.raw("hidden_check", {"passed": 2, "failed": 0, "total": 2, "checks": []})
    assert LedgerFacts(lb.ledger()).ground_truth_success() is True


def test_ground_truth_from_counts_failed(lb: SyntheticLedger) -> None:
    lb.raw("hidden_check", {"passed": 1, "failed": 1, "total": 2, "checks": []})
    assert LedgerFacts(lb.ledger()).ground_truth_success() is False


def test_ground_truth_none_when_zero_total(lb: SyntheticLedger) -> None:
    lb.raw("hidden_check", {"passed": 0, "failed": 0, "total": 0, "checks": []})
    assert LedgerFacts(lb.ledger()).ground_truth_success() is None


def test_diff_accessors_skip_malformed_entries(lb: SyntheticLedger) -> None:
    lb.raw(
        "diff",
        {
            "files": [{"path": "a.py", "status": "M"}, "junk"],
            "dependency_changes": [{"name": "x", "change": "added"}, 3],
            "source": "snapshot",
        },
    )
    facts = LedgerFacts(lb.ledger())
    assert [f["path"] for f in facts.diff_files()] == ["a.py"]
    assert [c["name"] for c in facts.dependency_changes()] == ["x"]
