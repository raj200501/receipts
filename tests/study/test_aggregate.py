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


def test_pilot_summary_per_arm() -> None:
    timing = {"wall_s": 100.0, "model_wall_s": 80.0, "input_tokens": 10, "output_tokens": 2}
    records = [
        record("r1", CLAIMS, turns=4, **timing),
        record(
            "r2",
            [],
            report="",
            stop_reason="max_turns",
            turns=25,
            false_success=False,
            **{**timing, "wall_s": 300.0},
        ),
        record("r3", CLAIMS[:1], config_id="ma-y", model="n", **timing),
    ]
    out = aggregate.pilot_summary_artifact(records, {"git_sha": "x"})
    x = out["arms"]["ma-x"]
    assert x["n_runs"] == 2
    assert x["reported"] == 1
    assert x["stop_reasons"] == {"finished": 1, "max_turns": 1}
    assert x["false_success"] == 1
    assert x["claims"] == 2
    assert x["turns"] == {"median": 14.5, "mean": 14.5, "max": 25.0, "total": 29.0}
    assert x["wall_s"]["total"] == 400.0
    assert x["input_tokens"] == 20
    assert out["arms"]["ma-y"]["model"] == "n"
    assert out["provenance"] == {"git_sha": "x"}
    assert aggregate._spread([]) == {"median": 0.0, "mean": 0.0, "max": 0.0, "total": 0.0}
