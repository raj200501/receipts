"""Tests for run aggregation and the E1 and E4 row contract.

Every record, rescoring result, and instrument record here is SYNTHETIC test data
written by hand; none comes from an agent run, and nothing computed here is a result.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from receipts.ledger.events import sha256_text
from receipts.study import aggregate
from receipts.study.rescore import Rescored


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
        "mitigation": "none",
        "stop_reason": "finished",
        "turns": 5,
        "report": report,
        "success_reported": True,
        "ground_truth_success": False,
        "false_success": True,
        "omissions": 1,
        "claims": claims,
        "input_tokens": 120,
        "output_tokens": 30,
        "model_wall_s": 80.5,
        "wall_s": 100.25,
        "drafts": [],
        "hook_checks": [],
        "provenance": {
            "git_sha": "1" * 40,
            "code": "snapshot",
            "snapshot_of": "1" * 40,
            "task_tree_sha256": "2" * 64,
        },
    }
    return {**base, **over}


CLAIMS = [
    {"claim_id": "c0", "type": "tests_pass", "verdict": "contradicted"},
    {"claim_id": "c1", "type": "file_modified", "verdict": "supported"},
]

#: SYNTHETIC rescored claims: the run-time verdict of c0 is overturned at banking.
RESCORED_CLAIMS = [
    {
        "claim_id": "c0",
        "claim_type": "tests_pass",
        "text": "All tests pass.",
        "verdict": "supported",
        "evidence": [3, 4],
    },
    {
        "claim_id": "c1",
        "claim_type": "file_modified",
        "text": "Updated calc.py.",
        "verdict": "contradicted",
        "evidence": [5],
    },
]

#: A SYNTHETIC instrument record (the shape of ``rescore.instrument_record``).
INSTRUMENT: dict[str, Any] = {
    "commit": "9" * 40,
    "paths": ["src/receipts/claims", "src/receipts/verify"],
    "trees": {"src/receipts/claims": "a" * 40, "src/receipts/verify": "b" * 40},
    "dirty": False,
    "uncommitted": [],
}


def rescored(run_id: str, report: str = "Done.", **over: Any) -> Rescored:
    """A SYNTHETIC rescoring result for ``run_id``."""
    fields: dict[str, Any] = {
        "run_id": run_id,
        "report": report,
        "stop_reason": "finished",
        "turns": 5,
        "claims": copy.deepcopy(RESCORED_CLAIMS),
        "success_reported": False,
        "ground_truth_success": True,
        "false_success": False,
        "omissions": 2,
        "runtime_agrees": False,
    }
    fields.update(over)
    return Rescored(**fields)


def pair(run_id: str, report: str = "Done.", **over: Any) -> tuple[dict[str, Any], Rescored]:
    return record(run_id, CLAIMS, report), rescored(run_id, report, **over)


E1_KEYS = {
    "run_id",
    "config_id",
    "model",
    "model_family",
    "task_id",
    "conditions",
    "seed",
    "synthetic",
    "included",
    "completed",
    "false_success",
    "success_reported",
    "ground_truth_success",
    "omissions",
    "claims",
    "any_contradicted",
    "mitigation",
    "stop_reason",
    "turns",
    "report_sha256",
    "run_code",
    "task_tree_sha256",
    "instrument",
    "instrument_dirty",
    "runtime_agrees",
}
E4_KEYS = E1_KEYS | {
    "input_tokens",
    "output_tokens",
    "wall_s",
    "model_wall_s",
    "hook_checks",
    "drafts",
}


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


def test_e1_row_contract_comes_from_the_rescoring() -> None:
    (row,) = aggregate.e1_rows([pair("a")], INSTRUMENT)
    assert set(row) == E1_KEYS
    # Identity and design fields from run.json.
    assert (row["run_id"], row["config_id"], row["model"], row["task_id"]) == (
        "a",
        "ma-x",
        "m",
        "t1",
    )
    assert row["model_family"] == "f" and row["seed"] == 1
    assert row["conditions"] == {"M1": "attainable"} and row["synthetic"] is False
    assert row["mitigation"] == "none"
    # Outcomes from the rescoring, never from the run-time fields of run.json.
    assert row["false_success"] is False and row["success_reported"] is False
    assert row["ground_truth_success"] is True and row["omissions"] == 2
    assert row["claims"] == RESCORED_CLAIMS
    assert row["included"] is True and row["completed"] is True
    assert row["stop_reason"] == "finished" and row["turns"] == 5
    assert row["report_sha256"] == sha256_text("Done.")
    assert row["runtime_agrees"] is False
    # Provenance of the run and of the banking checkout.
    assert row["run_code"] == {
        "git_sha": "1" * 40,
        "code": "snapshot",
        "snapshot_of": "1" * 40,
        "uncommitted_src": None,
    }
    assert row["task_tree_sha256"] == "2" * 64
    assert row["instrument"] == INSTRUMENT and row["instrument_dirty"] is False
    assert row["any_contradicted"] is None  # no held-out evaluation given
    json.dumps(row, allow_nan=False)


def test_inclusion_and_completion_follow_the_rescored_report_and_stop_reason() -> None:
    rows = aggregate.e1_rows(
        [
            pair("a"),
            pair("b", stop_reason="finished_at_cap", turns=17),
            pair("c", report="  \n", stop_reason="finished"),
            pair("d", report="", stop_reason="max_turns"),
        ],
        INSTRUMENT,
    )
    assert [(r["included"], r["completed"]) for r in rows] == [
        (True, True),
        (True, False),
        (False, False),
        (False, False),
    ]
    assert [r["run_id"] for r in rows] == ["a", "b", "c", "d"]
    assert rows[1]["turns"] == 17 and rows[1]["stop_reason"] == "finished_at_cap"


def test_any_contradicted_counts_only_valid_types() -> None:
    given = [pair("a")]
    assert aggregate.e1_rows(given, INSTRUMENT, ["file_modified"])[0]["any_contradicted"] is True
    assert aggregate.e1_rows(given, INSTRUMENT, ["tests_pass"])[0]["any_contradicted"] is False
    assert aggregate.e1_rows(given, INSTRUMENT, [])[0]["any_contradicted"] is False
    assert aggregate.e1_rows(given, INSTRUMENT, None)[0]["any_contradicted"] is None


def test_instrument_dirty_marks_every_row() -> None:
    dirty = {**INSTRUMENT, "dirty": True, "uncommitted": ["src/receipts/verify/x.py"]}
    rows = aggregate.e1_rows([pair("a"), pair("b")], dirty)
    assert [r["instrument_dirty"] for r in rows] == [True, True]
    assert rows[0]["instrument"]["uncommitted"] == ["src/receipts/verify/x.py"]
    forced = aggregate.e1_rows([pair("a")], INSTRUMENT, instrument_dirty=True)
    assert forced[0]["instrument_dirty"] is True
    # A dirty instrument record is never reported clean.
    assert aggregate.e1_rows([pair("a")], dirty, instrument_dirty=False)[0]["instrument_dirty"]


def test_rows_do_not_share_mutable_state_with_their_inputs() -> None:
    given = pair("a")
    (row,) = aggregate.e1_rows([given], INSTRUMENT)
    row["claims"][0]["verdict"] = "changed"
    row["instrument"]["trees"]["src/receipts/claims"] = "changed"
    assert given[1].claims[0]["verdict"] == "supported"
    assert INSTRUMENT["trees"]["src/receipts/claims"] == "a" * 40


@pytest.mark.parametrize(
    ("provenance", "expected"),
    [
        (
            {"git_sha": "s", "code": "snapshot", "snapshot_of": "s"},
            {"git_sha": "s", "code": "snapshot", "snapshot_of": "s", "uncommitted_src": None},
        ),
        (
            {
                "git_sha": "w",
                "code": "working tree",
                "uncommitted_at_start": [
                    "docs/PLAN.md",
                    "src/receipts/verify/checkers.py",
                    "docs/old.md -> src/receipts/new.py",
                    '"src/receipts/a b.py"',
                    "srcfoo/x.py",
                ],
            },
            {
                "git_sha": "w",
                "code": "working tree",
                "snapshot_of": None,
                "uncommitted_src": [
                    "src/receipts/verify/checkers.py",
                    "docs/old.md -> src/receipts/new.py",
                    '"src/receipts/a b.py"',
                ],
            },
        ),
        (
            {"git_sha": "w", "code": "working tree", "uncommitted_at_start": ["README.md"]},
            {"git_sha": "w", "code": "working tree", "snapshot_of": None, "uncommitted_src": []},
        ),
        ({}, {"git_sha": None, "code": None, "snapshot_of": None, "uncommitted_src": None}),
        (None, {"git_sha": None, "code": None, "snapshot_of": None, "uncommitted_src": None}),
    ],
)
def test_run_code_from_the_runs_provenance(
    provenance: Mapping[str, Any] | None, expected: Mapping[str, Any]
) -> None:
    assert aggregate.run_code(provenance) == expected


@pytest.mark.parametrize(
    "provenance",
    [
        {"git_sha": 5},
        {"code": ["snapshot"]},
        {"snapshot_of": 1},
        {"uncommitted_at_start": "src/x.py"},
        {"uncommitted_at_start": [3]},
    ],
)
def test_run_code_refuses_malformed_provenance(provenance: Mapping[str, Any]) -> None:
    with pytest.raises(ValueError, match="provenance"):
        aggregate.run_code(provenance)


def test_rows_refuse_a_provenance_that_is_not_an_object() -> None:
    rec, res = pair("a")
    rec["provenance"] = ["SYNTHETIC"]
    with pytest.raises(ValueError, match="run 'a': provenance must be an object"):
        aggregate.e1_rows([(rec, res)], INSTRUMENT)


def test_run_row_refuses_a_study_without_a_row_contract() -> None:
    rec, res = pair("a")
    with pytest.raises(ValueError, match="no row contract"):
        aggregate.run_row(rec, res, study="e2", instrument=INSTRUMENT)


def test_task_tree_is_null_when_the_run_did_not_record_it() -> None:
    rec, res = pair("a")
    del rec["provenance"]["task_tree_sha256"]
    assert aggregate.e1_rows([(rec, res)], INSTRUMENT)[0]["task_tree_sha256"] is None
    rec["provenance"]["task_tree_sha256"] = 7
    with pytest.raises(ValueError, match="task_tree_sha256"):
        aggregate.e1_rows([(rec, res)], INSTRUMENT)


def test_e4_rows_add_cost_and_hook_fields() -> None:
    checks = [{"latency_s": 0.12, "claims": 2, "contradicted": 1, "blocked": True}]
    rec = record(
        "h1",
        CLAIMS,
        mitigation="hook",
        hook_checks=checks,
        drafts=["Done. All tests pass."],
    )
    (row,) = aggregate.e4_rows([(rec, rescored("h1"))], INSTRUMENT, ["tests_pass"])
    assert set(row) == E4_KEYS
    assert row["mitigation"] == "hook"
    assert (row["input_tokens"], row["output_tokens"]) == (120, 30)
    assert (row["wall_s"], row["model_wall_s"]) == (100.25, 80.5)
    assert row["hook_checks"] == checks and row["drafts"] == ["Done. All tests pass."]
    assert row["claims"] == RESCORED_CLAIMS and row["any_contradicted"] is False
    row["hook_checks"][0]["blocked"] = False
    assert checks[0]["blocked"] is True


def test_e1_rows_refuse_runs_with_a_mitigation() -> None:
    rec, res = pair("a")
    rec["mitigation"] = "hook"
    with pytest.raises(ValueError, match="mitigation"):
        aggregate.e1_rows([(rec, res)], INSTRUMENT)
    del rec["mitigation"]  # a record from before the field existed ran no mitigation
    assert aggregate.e1_rows([(rec, res)], INSTRUMENT)[0]["mitigation"] == "none"
    rec["mitigation"] = "magic"
    with pytest.raises(ValueError, match="mitigation"):
        aggregate.e4_rows([(rec, res)], INSTRUMENT)


def test_rows_refuse_a_rescoring_of_another_run() -> None:
    rec, _ = pair("a")
    with pytest.raises(ValueError, match="rescoring of run 'b'"):
        aggregate.e1_rows([(rec, rescored("b"))], INSTRUMENT)
    with pytest.raises(ValueError, match="report"):
        aggregate.e1_rows([(rec, rescored("a", report="Other."))], INSTRUMENT)


def test_rows_refuse_repeated_run_ids() -> None:
    with pytest.raises(ValueError, match="repeats"):
        aggregate.e1_rows([pair("a"), pair("a")], INSTRUMENT)


@pytest.mark.parametrize(
    "instrument",
    [
        {},
        {**INSTRUMENT, "commit": None},
        {**INSTRUMENT, "paths": "src"},
        {**INSTRUMENT, "trees": None},
        {**INSTRUMENT, "dirty": "no"},
        {**INSTRUMENT, "uncommitted": None},
    ],
)
def test_rows_refuse_a_malformed_instrument_record(instrument: Mapping[str, Any]) -> None:
    with pytest.raises(ValueError, match="instrument"):
        aggregate.e1_rows([pair("a")], instrument)


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_id", None), ("config_id", 3), ("family", None), ("seed", True), ("conditions", [])],
)
def test_rows_refuse_malformed_records(field: str, value: Any) -> None:
    rec, res = pair("a")
    rec[field] = value
    with pytest.raises(ValueError, match=field):
        aggregate.e1_rows([(rec, res)], INSTRUMENT)


def test_e4_rows_refuse_records_without_cost_fields() -> None:
    rec, res = pair("a")
    del rec["wall_s"]
    with pytest.raises(ValueError, match="wall_s"):
        aggregate.e4_rows([(rec, res)], INSTRUMENT)


def test_rows_carry_the_record_synthetic_flag(tmp_path: Path) -> None:
    rows = aggregate.e1_rows(
        [pair("r1"), (record("r2", CLAIMS, synthetic=True), rescored("r2"))], INSTRUMENT
    )
    assert [r["synthetic"] for r in rows] == [False, True]
    out = tmp_path / "x" / "runs.jsonl"
    aggregate.write_jsonl(out, rows)
    assert [json.loads(line)["run_id"] for line in out.read_text().splitlines()] == ["r1", "r2"]


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
