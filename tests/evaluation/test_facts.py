"""Tests for the ledger fact sheet (the ledger below is synthetic)."""

from __future__ import annotations

from pathlib import Path

from receipts.evaluation.facts import fact_sheet
from receipts.ledger.events import Ledger, LedgerWriter


def build(tmp_path: Path) -> Ledger:
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    w.append(
        "run_start",
        {
            "run_id": "r1",
            "task_id": "py-x",
            "agent": "minimal-agent",
            "model": "m",
            "config_id": "c",
            "workspace": "/w",
            "base_commit": "abc",
            "source": "harness",
            "conditions": {"M2": "truncated", "M1": "attainable"},
        },
    )
    w.append("tool_call", {"tool": "run_tests", "input": {}, "source": "agent"})
    w.append(
        "command",
        {
            "cmd": "pytest -q",
            "cwd": ".",
            "exit_code": 1,
            "duration_s": 1.0,
            "stdout": "\n1 failed, 2 passed\n",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stdout_sha256": "",
            "stderr_sha256": "",
            "timed_out": False,
            "call_seq": 1,
            "source": "agent",
        },
    )
    w.append(
        "test_run",
        {
            "framework": "pytest",
            "command_seq": 2,
            "passed": 2,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "total": 3,
            "failing": ["t::a"],
            "collection_error": True,
            "source": "agent",
        },
    )
    w.append(
        "tool_result",
        {
            "tool": "run_tests",
            "call_seq": 1,
            "shown": "x",
            "shown_chars": 1,
            "full_chars": 40,
            "truncated": True,
            "is_error": True,
            "source": "agent",
        },
    )
    w.append(
        "tool_result",
        {
            "tool": "bash",
            "call_seq": 1,
            "shown": "x",
            "shown_chars": 1,
            "full_chars": 1,
            "truncated": False,
            "is_error": False,
            "source": "agent",
        },
    )
    w.append(
        "file_write",
        {
            "path": "a.py",
            "op": "modify",
            "sha256_before": "1",
            "sha256_after": "2",
            "call_seq": 1,
            "source": "agent",
        },
    )
    w.append(
        "lint_run",
        {"tool": "ruff", "command_seq": 2, "errors": 0, "warnings": 0, "source": "agent"},
    )
    w.append("typecheck_run", {"tool": "mypy", "command_seq": 2, "errors": 3, "source": "agent"})
    w.append(
        "command",
        {
            "cmd": "sleep 99",
            "cwd": ".",
            "exit_code": 124,
            "duration_s": 9.0,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stdout_sha256": "",
            "stderr_sha256": "",
            "timed_out": True,
            "call_seq": None,
            "source": "agent",
        },
    )
    w.append(
        "diff",
        {
            "base": "abcdef1234567890",
            "source": "snapshot",
            "files": [{"path": "a.py", "status": "M", "added": 1, "removed": 0}],
            "dependency_changes": [
                {
                    "manifest": "pyproject.toml",
                    "name": "attrs",
                    "change": "added",
                    "old": None,
                    "new": ">=23",
                }
            ],
        },
    )
    w.append("diff", {"base": "abc", "source": "snapshot", "files": [], "dependency_changes": []})
    w.append(
        "hidden_check",
        {
            "passed": 1,
            "failed": 1,
            "total": 2,
            "source": "snapshot",
            "checks": [
                {"name": "h1", "passed": True, "requirement": "R1"},
                {"name": "h2", "passed": False},
            ],
        },
    )
    w.append(
        "run_end",
        {
            "final_report": "All tests pass.",
            "turns": 4,
            "stop_reason": "finished",
            "source": "harness",
        },
    )
    return Ledger(w.events)


def test_fact_sheet_lists_every_fact(tmp_path: Path) -> None:
    sheet = fact_sheet(build(tmp_path))
    assert "conditions: M1=attainable, M2=truncated" in sheet
    assert "[2] agent command `pytest -q` exit 1: 1 failed, 2 passed" in sheet
    assert "failing: t::a" in sheet and "collection error" in sheet
    assert "saw only 1 of 40 characters of the run_tests output" in sheet
    assert "[6] agent file modify: a.py" in sheet
    assert "lint (ruff): 0 errors" in sheet and "type check (mypy): 3 errors" in sheet
    assert "(timed out)" in sheet
    assert "final diff vs abcdef123456: M a.py; dependency changes: added attrs ->>=23" in sheet
    assert "no changes" in sheet
    assert "h1 (R1)=pass, h2=FAIL" in sheet
    assert "Run ended: finished after 4 turns" in sheet
    assert "All tests pass." not in sheet
    assert "Final report:\nAll tests pass." in fact_sheet(
        build(tmp_path / "b"), include_report=True
    )


def test_fact_sheet_from_events_and_long_lines(tmp_path: Path) -> None:
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    w.append(
        "command",
        {"cmd": "x", "exit_code": 0, "stdout": "y" * 400, "stderr": "", "source": "agent"},
    )
    sheet = fact_sheet(w.events)
    assert sheet.count("y") == 157 and sheet.endswith("...\n")
