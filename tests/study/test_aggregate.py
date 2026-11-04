"""Tests for run aggregation (records below are synthetic)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from receipts.study import aggregate


def record(
    run_id: str, claims: list[dict[str, Any]], report: str = "Done.", **over: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": run_id,
        "task_id": "t1",
        "config_id": "ma-x",
        "model": "m",
        "family": "f",
        "conditions": {"M1": "attainable"},
        "seed": 1,
        "stop_reason": "finished",
        "turns": 5,
        "report": report,
        "success_reported": True,
        "ground_truth_success": False,
        "false_success": True,
        "omissions": 1,
        "claims": claims,
    }
    return {**base, **over}


CLAIMS = [
    {"claim_id": "c0", "type": "tests_pass", "verdict": "contradicted"},
    {"claim_id": "c1", "type": "file_modified", "verdict": "supported"},
]


def test_load_and_smoke_artifact(tmp_path: Path) -> None:
    for rid in ("b", "a"):
        (tmp_path / rid).mkdir()
        (tmp_path / rid / "run.json").write_text(json.dumps(record(rid, CLAIMS)))
    records = aggregate.load_records(tmp_path)
    assert [r["run_id"] for r in records] == ["a", "b"]
    smoke = aggregate.smoke_runs_artifact(records, {"git_sha": "x"})
    assert smoke["runs"][0]["synthetic"] is False and smoke["runs"][0]["agent"] == "minimal-agent/m"
    assert smoke["provenance"] == {"git_sha": "x"}


def test_claim_type_counts() -> None:
    records = [record("a", CLAIMS), record("b", [CLAIMS[0]]), record("c", [])]
    counts = aggregate.claim_type_counts_artifact(records, {})
    assert counts["counts"] == {"file_modified": 1, "tests_pass": 2}
    assert counts["source_runs"] == ["a", "b"]


def test_e1_rows_inclusion_and_valid_types(tmp_path: Path) -> None:
    rows = aggregate.e1_rows(
        [record("a", CLAIMS), record("b", [], report="  ", stop_reason="max_turns")],
        valid_types=["file_modified"],
    )
    assert rows[0]["included"] and rows[0]["completed"] and not rows[0]["any_contradicted"]
    assert rows[0]["model_family"] == "f" and rows[0]["synthetic"] is False
    assert not rows[1]["included"] and not rows[1]["completed"]
    assert aggregate.e1_rows([record("a", CLAIMS)])[0]["any_contradicted"] is True
    out = tmp_path / "x" / "runs.jsonl"
    aggregate.write_jsonl(out, rows)
    assert [json.loads(line)["run_id"] for line in out.read_text().splitlines()] == ["a", "b"]
