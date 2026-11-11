"""Tests for tools/bank_study.py: e1 and e4 banking re-verify every run (DECISIONS D42).

Each test works in a SYNTHETIC scratch checkout (a temporary git repository). Its only
real inputs are read-only copies of one committed task directory and of that task's
committed smoke run (a REAL ma-qwen7b run), filed under the scratch checkout's study
directories so the banking code has a real ledger to rescore. The rows, failure logs,
and seeded evaluations the tests write are SYNTHETIC test output, never E1 or E4
results, and nothing here touches the real artifacts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import bank_study
from receipts.evaluation import e0
from receipts.study import aggregate, rescore

ROOT = Path(__file__).resolve().parents[2]
TASK = "py-api-docs"
RUN_ID = f"smoke-{TASK}-ma-qwen7b"
REAL_RUN = ROOT / "artifacts" / "studies" / "smoke" / "runs" / RUN_ID
STUDIES = ("smoke", "pilot", "e1", "e4")
Commit = Callable[[Path, str], str]


@pytest.fixture
def checkout(git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A SYNTHETIC scratch checkout holding copies of one REAL task and its smoke run."""
    shutil.copytree(ROOT / "bench" / "tasks" / TASK, git_repo / "bench" / "tasks" / TASK)
    for study in STUDIES:
        shutil.copytree(REAL_RUN, git_repo / "artifacts" / "studies" / study / "runs" / RUN_ID)
    (git_repo / "README.md").write_text("SYNTHETIC scratch checkout for bank_study tests\n")
    commit(git_repo, "SYNTHETIC scratch checkout")
    monkeypatch.setattr(bank_study, "ROOT", git_repo)
    monkeypatch.setattr(bank_study, "imported_src", lambda: git_repo / "src")
    return git_repo


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def outputs(root: Path, study: str) -> list[Path]:
    """Every file the banking of ``study`` writes."""
    return [
        root / "artifacts" / study / "runs.jsonl",
        root / "artifacts" / study / "runs.provenance.json",
        root / "artifacts" / "studies" / study / "failures.jsonl",
    ]


def seeded_eval(root: Path, split: str = "heldout") -> Path:
    """Write a SYNTHETIC seeded evaluation in which only feature_implemented is valid."""
    items = [
        {
            "claim_type": "feature_implemented",
            "gold_verdict": "supported",
            "pred_verdict": "supported",
        }
        for _ in range(12)
    ] + [{"claim_type": "file_modified", "gold_verdict": "supported", "pred_verdict": "supported"}]
    data = {
        "split": split,
        "synthetic_reports": True,
        "items": items,
        "instrument": {"commit": "a" * 40, "paths": list(e0.SCORING_PATHS), "trees": {}},
    }
    path = root / bank_study.SEEDED_EVAL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_e1_banks_rows_from_the_rescoring(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bank_study.main(["e1"]) == 0
    rows = read_rows(checkout / "artifacts" / "e1" / "runs.jsonl")
    record = json.loads((REAL_RUN / "run.json").read_text(encoding="utf-8"))
    run_dir = checkout / "artifacts" / "studies" / "e1" / "runs" / RUN_ID
    expected = aggregate.e1_rows(
        [(record, rescore.rescore_run(run_dir, rescore.task_requirements(checkout, TASK)))],
        rescore.instrument_record(checkout),
    )
    assert rows == json.loads(json.dumps(expected))
    (row,) = rows
    assert row["run_id"] == RUN_ID and row["mitigation"] == "none"
    assert [c["claim_type"] for c in row["claims"]] == [c["type"] for c in record["claims"]]
    assert all(
        set(c) == {"claim_id", "claim_type", "text", "verdict", "evidence"} for c in row["claims"]
    )
    assert row["instrument"]["commit"] == e0.head_commit(checkout)
    assert row["instrument"]["paths"] == list(rescore.INSTRUMENT_RECORD_PATHS)
    assert row["instrument_dirty"] is False and row["any_contradicted"] is None
    assert row["run_code"]["code"] == "snapshot"
    assert row["task_tree_sha256"] == record["provenance"]["task_tree_sha256"]

    side = json.loads((checkout / "artifacts" / "e1" / "runs.provenance.json").read_text())
    rows_bytes = (checkout / "artifacts" / "e1" / "runs.jsonl").read_bytes()
    assert side["rows"] == "artifacts/e1/runs.jsonl"
    assert side["rows_sha256"] == hashlib.sha256(rows_bytes).hexdigest()
    assert side["runs_dir"] == "artifacts/studies/e1/runs"
    assert side["allow_dirty"] is False and side["instrument_dirty"] is False
    assert side["valid_types"] is None and side["failures"] is None
    assert side["runtime_disagreements"] == ([] if row["runtime_agrees"] else [RUN_ID])
    prov = side["provenance"]
    assert prov["git_sha"] == e0.head_commit(checkout) and prov["study"] == "e1"
    assert prov["command"] and prov["created"] and prov["plan_sha256"] == ""
    assert prov["instrument"] == row["instrument"]
    assert prov["seeded_eval"] is None and prov["seeded_eval_sha256"] is None
    assert "e1: banked 1 run(s)" in capsys.readouterr().out
    assert not (checkout / "artifacts" / "studies" / "e1" / "failures.jsonl").exists()


def test_e4_banks_rows_with_cost_and_hook_fields(checkout: Path) -> None:
    assert bank_study.main(["e4"]) == 0
    (row,) = read_rows(checkout / "artifacts" / "e4" / "runs.jsonl")
    record = json.loads((REAL_RUN / "run.json").read_text(encoding="utf-8"))
    assert row["input_tokens"] == record["input_tokens"]
    assert row["wall_s"] == record["wall_s"] and row["model_wall_s"] == record["model_wall_s"]
    assert row["hook_checks"] == record["hook_checks"] and row["drafts"] == record["drafts"]
    side = json.loads((checkout / "artifacts" / "e4" / "runs.provenance.json").read_text())
    assert side["rows"] == "artifacts/e4/runs.jsonl" and side["provenance"]["study"] == "e4"


def test_any_contradicted_uses_the_held_out_valid_types(checkout: Path) -> None:
    path = seeded_eval(checkout)
    assert bank_study.main(["e1"]) == 0
    (row,) = read_rows(checkout / "artifacts" / "e1" / "runs.jsonl")
    contradicted = {c["claim_type"] for c in row["claims"] if c["verdict"] == "contradicted"}
    assert row["any_contradicted"] is ("feature_implemented" in contradicted)
    side = json.loads((checkout / "artifacts" / "e1" / "runs.provenance.json").read_text())
    assert side["valid_types"] == ["feature_implemented"]  # file_modified has one gold claim
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert side["provenance"]["seeded_eval"] == bank_study.SEEDED_EVAL
    assert side["provenance"]["seeded_eval_sha256"] == digest

    seeded_eval(checkout, split="dev")  # not the held-out evaluation: not used
    assert bank_study.main(["e1"]) == 0
    (row,) = read_rows(checkout / "artifacts" / "e1" / "runs.jsonl")
    side = json.loads((checkout / "artifacts" / "e1" / "runs.provenance.json").read_text())
    assert row["any_contradicted"] is None and side["provenance"]["seeded_eval_sha256"] is None


def test_a_malformed_held_out_evaluation_is_refused(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seeded_eval(checkout)
    data = json.loads(path.read_text())
    data["items"][0]["pred_verdict"] = "maybe"
    path.write_text(json.dumps(data))
    assert bank_study.main(["e1"]) == 2
    assert "pred_verdict" in capsys.readouterr().err
    assert not any(p.exists() for p in outputs(checkout, "e1"))


def test_a_dirty_instrument_is_refused_unless_allowed(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = checkout / "src" / "receipts" / "verify" / "extra.py"
    extra.parent.mkdir(parents=True)
    extra.write_text("SYNTHETIC = True\n")
    assert bank_study.main(["e1"]) == 2
    err = capsys.readouterr().err
    assert "src/receipts/verify/extra.py" in err and "--allow-dirty" in err
    assert not any(p.exists() for p in outputs(checkout, "e1"))

    assert bank_study.main(["e1", "--allow-dirty"]) == 0
    (row,) = read_rows(checkout / "artifacts" / "e1" / "runs.jsonl")
    assert row["instrument_dirty"] is True and row["instrument"]["dirty"] is True
    assert row["instrument"]["uncommitted"] == ["src/receipts/verify/extra.py"]
    side = json.loads((checkout / "artifacts" / "e1" / "runs.provenance.json").read_text())
    assert side["allow_dirty"] is True and side["instrument_dirty"] is True
    assert "exploratory" in capsys.readouterr().out


def test_uncommitted_banking_code_is_refused_unless_allowed(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (checkout / "tools").mkdir()
    (checkout / "tools" / "bank_study.py").write_text("# SYNTHETIC uncommitted copy\n")
    assert bank_study.main(["e4"]) == 2
    assert "tools/bank_study.py" in capsys.readouterr().err
    assert not any(p.exists() for p in outputs(checkout, "e4"))
    assert bank_study.main(["e4", "--allow-dirty"]) == 0
    (row,) = read_rows(checkout / "artifacts" / "e4" / "runs.jsonl")
    assert row["instrument"]["dirty"] is False  # the instrument itself is clean
    assert row["instrument_dirty"] is True  # but the rows came from uncommitted code


def test_receipts_imported_from_another_tree_is_refused(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bank_study, "imported_src", lambda: ROOT / "src")
    assert bank_study.main(["e1", "--allow-dirty"]) == 2
    assert "imported from" in capsys.readouterr().err
    assert not any(p.exists() for p in outputs(checkout, "e1"))


def test_the_real_imported_src_is_this_checkouts_src() -> None:
    assert bank_study.imported_src() == (ROOT / "src").resolve()


def test_a_run_that_does_not_rescore_stops_the_banking(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = checkout / "artifacts" / "studies" / "e1" / "runs" / RUN_ID / "run.json"
    data = json.loads(path.read_text())
    data["report"] = "SYNTHETIC replacement report: all tests pass."
    path.write_text(json.dumps(data))
    assert bank_study.main(["e1"]) == 2
    err = capsys.readouterr().err
    assert RUN_ID in err and "report differs" in err
    assert not any(p.exists() for p in outputs(checkout, "e1"))


def test_task_files_changed_since_the_run_are_refused(
    checkout: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    toml = checkout / "bench" / "tasks" / TASK / "task.toml"
    toml.write_text(toml.read_text() + "\n# SYNTHETIC change after the run\n")
    commit(checkout, "SYNTHETIC task change")
    for flags in ([], ["--allow-dirty"]):
        assert bank_study.main(["e1", *flags]) == 2
        err = capsys.readouterr().err
        assert RUN_ID in err and "task files" in err
    assert not any(p.exists() for p in outputs(checkout, "e1"))


def failure_log(root: Path, study: str, entries: list[dict[str, Any]]) -> Path:
    path = root / "runs" / study / "failures.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


#: SYNTHETIC failure entries in the run_study.py log format (with a trace).
FAILURES = [
    {
        "run_id": "e1-0001",
        "time": "2026-11-05T01:00:00+00:00",
        "attempt": 1,
        "error": "RuntimeError: SYNTHETIC server error",
        "trace": "Traceback (most recent call last): SYNTHETIC",
    },
    {
        "run_id": "e1-0001",
        "at": "2026-11-05T01:00:00+00:00",
        "attempt": 2,
        "error": "RuntimeError: SYNTHETIC server error",
        "trace": "Traceback: SYNTHETIC",
        "server": "SYNTHETIC extra key",
    },
]


def test_failures_are_banked_without_trace(checkout: Path) -> None:
    failure_log(checkout, "e1", FAILURES)
    assert bank_study.main(["e1"]) == 0
    banked = read_rows(checkout / "artifacts" / "studies" / "e1" / "failures.jsonl")
    assert banked == [{k: v for k, v in e.items() if k != "trace"} for e in FAILURES]
    side = json.loads((checkout / "artifacts" / "e1" / "runs.provenance.json").read_text())
    path = checkout / "artifacts" / "studies" / "e1" / "failures.jsonl"
    assert side["failures"] == {
        "source": "runs/e1/failures.jsonl",
        "banked": "artifacts/studies/e1/failures.jsonl",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entries": 2,
        "added": 2,
    }
    assert "trace" not in path.read_text()


def test_failures_banked_earlier_are_kept(checkout: Path) -> None:
    earlier = {"run_id": "e1-0002", "time": "t0", "attempt": 1, "error": "SYNTHETIC"}
    banked_path = checkout / "artifacts" / "studies" / "e1" / "failures.jsonl"
    banked_path.parent.mkdir(parents=True, exist_ok=True)
    banked_path.write_text(json.dumps(earlier) + "\n")
    # The log was reset since (it no longer holds the earlier entry), and it logged the
    # same failure line twice: both copies count, the earlier entry stays.
    twice = [FAILURES[0], FAILURES[0]]
    failure_log(checkout, "e1", twice)
    assert bank_study.main(["e1"]) == 0
    stripped = {k: v for k, v in FAILURES[0].items() if k != "trace"}
    assert read_rows(banked_path) == [earlier, stripped, stripped]
    # Banking again from the same log adds nothing.
    assert bank_study.main(["e1"]) == 0
    assert read_rows(banked_path) == [earlier, stripped, stripped]
    side = json.loads((checkout / "artifacts" / "e1" / "runs.provenance.json").read_text())
    assert side["failures"]["entries"] == 3 and side["failures"]["added"] == 0


def test_banked_failures_stay_when_there_is_no_log(checkout: Path) -> None:
    banked_path = checkout / "artifacts" / "studies" / "e4" / "failures.jsonl"
    banked_path.parent.mkdir(parents=True, exist_ok=True)
    banked_path.write_text('{"run_id": "e4-0001", "attempt": 1, "error": "SYNTHETIC"}\n')
    before = banked_path.read_bytes()
    assert bank_study.main(["e4"]) == 0
    assert banked_path.read_bytes() == before
    side = json.loads((checkout / "artifacts" / "e4" / "runs.provenance.json").read_text())
    assert side["failures"] is None


@pytest.mark.parametrize(
    "line", ['{"run_id": "e1-1", "error"', "[1]", '{"error": "x"}', '{"run_id": ""}']
)
def test_a_malformed_failure_log_is_refused(
    checkout: Path, line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = checkout / "runs" / "e1" / "failures.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(FAILURES[0]) + "\n" + line + "\n")
    assert bank_study.main(["e1"]) == 2
    assert "runs/e1/failures.jsonl:2" in capsys.readouterr().err
    assert not any(p.exists() for p in outputs(checkout, "e1"))


def test_smoke_and_pilot_keep_their_outputs(checkout: Path) -> None:
    assert bank_study.main(["smoke"]) == 0
    smoke = json.loads((checkout / "artifacts" / "bench" / "smoke_runs.json").read_text())
    assert [r["run_id"] for r in smoke["runs"]] == [RUN_ID]
    assert (
        smoke["schema"] == "receipts.bench.smoke_runs/1" and smoke["provenance"]["study"] == "smoke"
    )
    assert bank_study.main(["pilot"]) == 0
    pilot = json.loads((checkout / "artifacts" / "studies" / "pilot" / "summary.json").read_text())
    assert pilot["arms"]["ma-qwen7b"]["n_runs"] == 1
    assert not (checkout / "artifacts" / "smoke").exists()
    with pytest.raises(SystemExit):
        bank_study.main(["smoke", "--allow-dirty"])
