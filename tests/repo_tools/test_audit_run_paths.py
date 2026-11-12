"""tools/audit_run_paths.py: the path audit of run ledgers from the command line.

The ledgers are SYNTHETIC test fixtures written with the real recorder; nothing runs
and nothing outside tmp_path is read or written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import audit_run_paths
from receipts.ledger.events import LedgerWriter
from receipts.ledger.recorder import Recorder

WS = "/home/synthetic/receipts/runs/work/smoke/run-1"


def run_dir(root: Path, *commands: str, banked: bool = False) -> Path:
    """A SYNTHETIC minimal-agent run whose agent ran ``commands`` with bash."""
    recorder = Recorder(LedgerWriter(root / "ledger.jsonl"))
    recorder.record_run_start(
        run_id=root.name,
        task_id="py-synthetic",
        agent="minimal-agent",
        model="synthetic-model",
        config_id="synthetic-arm",
        workspace=WS,
        base_commit="0" * 40,
    )
    for cmd in commands:
        seq = recorder.record_tool_call("bash", {"tool": "bash", "args": {"cmd": cmd}})
        recorder.record_tool_result(seq, "ok")
    if banked:
        (root / "run.json").write_text("{}", encoding="utf-8")
    return root


def test_clean_runs_exit_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = run_dir(tmp_path / "clean", "python3 -m pytest -q", banked=True)
    assert audit_run_paths.main([str(clean)]) == 0
    out = capsys.readouterr().out
    assert f"{clean} (banked;" in out and out.splitlines()[0].endswith("CLEAN")
    assert out.splitlines()[-1] == "audited 1 run(s): 1 clean, 0 with findings"


def test_a_finding_in_any_run_exits_1_and_names_the_seq(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = run_dir(tmp_path / "clean", "ls src")
    dirty = run_dir(tmp_path / "dirty", "ls", "cat /home/synthetic/receipts/private/notes.txt")
    assert audit_run_paths.main([str(clean), str(dirty / "ledger.jsonl")]) == 1
    out = capsys.readouterr().out
    assert "in progress, no run.json" in out
    assert "  seq 3 bash absolute: /home/synthetic/receipts/private/notes.txt" in out
    assert out.splitlines()[-1] == "audited 2 run(s): 1 clean, 1 with findings"


def test_a_run_without_a_ledger_is_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert audit_run_paths.main([str(tmp_path / "missing")]) == 1
    assert "no ledger" in capsys.readouterr().out


def test_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dirty = run_dir(tmp_path / "dirty", "cd / && ls")
    assert audit_run_paths.main(["--json", str(dirty)]) == 1
    (record,) = json.loads(capsys.readouterr().out)
    assert record["clean"] is False and record["workspace"] == WS
    assert {(f["seq"], f["kind"]) for f in record["findings"]} == {(1, "absolute"), (1, "cd")}
