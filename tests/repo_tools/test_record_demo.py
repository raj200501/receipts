"""Tests for tools/record_demo.py (copies banked runs into the demo fixtures)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import record_demo


def banked_run(root: Path, run_id: str = "pilot-000-ma-x", sha: str = "a" * 40) -> Path:
    run_dir = root / "artifacts" / "studies" / "pilot" / "runs" / run_id
    run_dir.mkdir(parents=True)
    start = {"kind": "run_start", "seq": 0, "data": {"agent": "minimal-agent"}}
    (run_dir / "ledger.jsonl").write_text(json.dumps(start) + "\n{}\n", encoding="utf-8")
    record = {
        "run_id": run_id,
        "task_id": "pilot-py-x",
        "config_id": "ma-x",
        "model": "m",
        "provenance": {"git_sha": sha},
    }
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    return run_dir


def test_record_copies_the_ledger_and_names_its_source(tmp_path: Path) -> None:
    run_dir = banked_run(tmp_path)
    fixtures = tmp_path / "fixtures"
    target = record_demo.record(run_dir, fixtures, tmp_path)
    ledger = (run_dir / "ledger.jsonl").read_bytes()
    assert (target / "ledger.jsonl").read_bytes() == ledger
    meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
    assert meta["task_id"] == "pilot-py-x"
    assert meta["agent"] == "minimal-agent"
    assert meta["model"] == "m"
    assert meta["recorded_from"] == (
        "artifacts/studies/pilot/runs/pilot-000-ma-x (run at aaaaaaaaaaaa)"
    )
    assert meta["ledger_sha256"] == hashlib.sha256(ledger).hexdigest()
    again = record_demo.record(run_dir, fixtures, tmp_path)
    assert again == target


def test_record_rejects_runs_that_are_not_banked(tmp_path: Path) -> None:
    run_dir = banked_run(tmp_path)
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    record["provenance"] = {}
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="git_sha"):
        record_demo.fixture_meta(run_dir, tmp_path)
    with pytest.raises(ValueError, match="not a banked run"):
        record_demo.fixture_meta(tmp_path / "missing", tmp_path)


def test_record_rejects_ledgers_without_run_start(tmp_path: Path) -> None:
    run_dir = banked_run(tmp_path)
    (run_dir / "ledger.jsonl").write_text('{"kind": "command"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="run_start"):
        record_demo.fixture_meta(run_dir, tmp_path)


def test_record_rejects_runs_outside_the_repository(tmp_path: Path) -> None:
    run_dir = banked_run(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="inside the repository"):
        record_demo.fixture_meta(run_dir, tmp_path / "repo")


def test_main_records_every_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(record_demo, "ROOT", tmp_path)
    monkeypatch.setattr(record_demo, "FIXTURES", tmp_path / "fixtures")
    first = banked_run(tmp_path, "r1")
    second = banked_run(tmp_path, "r2")
    monkeypatch.setattr(record_demo.record, "__defaults__", (tmp_path / "fixtures", tmp_path))
    assert record_demo.main([str(first), str(second)]) == 0
    assert sorted(p.name for p in (tmp_path / "fixtures").iterdir()) == ["r1", "r2"]
