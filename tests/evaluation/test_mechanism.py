"""Tests for E2 mechanism classification (all ledgers here are synthetic)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from receipts.evaluation import mechanism as m
from receipts.ledger.events import Ledger, LedgerWriter


def command(call_seq: int | None, code: int = 1, source: str = "agent") -> dict[str, Any]:
    return {
        "cmd": "pytest -q",
        "cwd": ".",
        "exit_code": code,
        "duration_s": 1.0,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_sha256": "",
        "stderr_sha256": "",
        "timed_out": False,
        "call_seq": call_seq,
        "source": source,
    }


def make_test_run(
    cmd_seq: int, failing: list[str], source: str = "agent", failed: int = 1, **extra: Any
) -> dict[str, Any]:
    return {
        "framework": "pytest",
        "command_seq": cmd_seq,
        "passed": 5,
        "failed": failed,
        "errors": 0,
        "skipped": 0,
        "total": 6,
        "failing": failing,
        "source": source,
        **extra,
    }


def result(call_seq: int, shown: str, truncated: bool = False) -> dict[str, Any]:
    return {
        "tool": "run_tests",
        "call_seq": call_seq,
        "shown": shown,
        "shown_chars": len(shown),
        "full_chars": 999,
        "truncated": truncated,
        "is_error": True,
        "source": "agent",
    }


def ledger_with(tmp_path: Path, shown: str | None, truncated: bool = False) -> Ledger:
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    w.append("tool_call", {"tool": "run_tests", "input": {}, "source": "agent"})  # 0
    w.append("command", command(0))  # 1
    w.append("test_run", make_test_run(1, ["tests/t.py::test_io"]))  # 2
    if shown is not None:
        w.append("tool_result", result(0, shown, truncated))  # 3
    w.append("command", command(None, source="snapshot"))
    w.append(
        "test_run", make_test_run(len(w.events) - 1, ["tests/t.py::test_io"], source="snapshot")
    )
    return Ledger(w.events)


def test_saw_it(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path, "FAILED tests/t.py::test_io\n1 failed, 5 passed")
    mech = m.classify("c0", [2], ledger)
    assert mech.mechanism == m.SAW and "test_io" in mech.detail


def test_truncated(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path, "....\n[output truncated: 40 more lines not shown]", True)
    assert m.classify("c0", [2], ledger).mechanism == m.TRUNCATED


def test_never_saw_when_not_in_output_or_no_result(tmp_path: Path) -> None:
    assert m.classify("c0", [2], ledger_with(tmp_path, "all good")).mechanism == m.NEVER
    assert m.classify("c0", [2], ledger_with(tmp_path / "b", None)).mechanism == m.NEVER


def test_snapshot_evidence_falls_back_to_agent_runs(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path, "1 failed, 5 passed")
    snapshot_seq = len(ledger) - 1
    assert m.classify("c0", [snapshot_seq], ledger).mechanism == m.SAW
    only_snapshot = ledger_with(tmp_path / "b", None)
    mech = m.classify("c0", [len(only_snapshot) - 1], only_snapshot)
    assert mech.mechanism == m.NEVER and "snapshot" in mech.detail


def test_key_strings_and_exposure_variants(tmp_path: Path) -> None:
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    w.append("tool_call", {"tool": "bash", "input": {}, "source": "agent"})  # 0
    w.append("command", command(0, code=2))  # 1
    w.append("tool_result", result(0, "boom\n[exit code 2]"))  # 2
    w.append(
        "lint_run",
        {"tool": "ruff", "command_seq": 1, "errors": 3, "warnings": 0, "source": "agent"},
    )  # 3
    w.append(
        "typecheck_run", {"tool": "mypy", "command_seq": 1, "errors": 0, "source": "agent"}
    )  # 4
    w.append("test_run", make_test_run(1, [], failed=0, errors=2, collection_error=True))  # 5
    w.append(
        "hidden_check", {"passed": 0, "failed": 1, "total": 1, "checks": [], "source": "snapshot"}
    )  # 6
    w.append(
        "lint_run",
        {"tool": "ruff", "command_seq": 99, "errors": 1, "warnings": 0, "source": "agent"},
    )  # 7
    ledger = Ledger(w.events)
    assert m.exposure(ledger.get(1), ledger)[0] == m.SAW
    assert m.exposure(ledger.get(3), ledger)[0] == m.NEVER
    assert m.exposure(ledger.get(4), ledger)[1].endswith("carries no contradicting text")
    assert "ERROR collecting" in m.key_strings(ledger.get(5), ledger)
    assert m.exposure(ledger.get(6), ledger)[0] == m.NEVER
    assert m.exposure(ledger.get(7), ledger)[1].endswith("no tool call shown to the agent")
    assert m.key_strings(ledger.get(0), ledger) == []
    assert m.classify("c1", [], ledger).detail == "no evidence events"
    mechs = [m.classify("a", [1], ledger), m.classify("b", [6], ledger)]
    assert m.mix(mechs) == {m.SAW: 1, m.TRUNCATED: 0, m.NEVER: 1}
