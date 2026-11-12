"""Tests for tools/bank_study.py: e1 and e4 banking re-verify every run (DECISIONS D42).

Each test works in a SYNTHETIC scratch checkout (a temporary git repository). Its only
real inputs are read-only copies of one committed task directory and of that task's
committed smoke run (a REAL ma-qwen7b run), filed under the scratch checkout's study
directories so the banking code has a real ledger to rescore. The rows, failure logs,
and seeded evaluations the tests write are SYNTHETIC test output, never E1 or E4
results, and nothing here touches the real artifacts.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import bank_study
from receipts.bench.canary import remove_canary
from receipts.bench.hashing import tree_sha256
from receipts.client.models import QWEN_CODER_7B
from receipts.client.server import LocalServer
from receipts.evaluation import e0
from receipts.study import aggregate, rescore
from receipts.study.plan import Plan, ServerRequirement, amend_plan, load_plan, write_plan

ROOT = Path(__file__).resolve().parents[2]
TASK = "py-api-docs"
RUN_ID = f"smoke-{TASK}-ma-qwen7b"
REAL_RUN = ROOT / "artifacts" / "studies" / "smoke" / "runs" / RUN_ID
SMOKE_PLAN = "artifacts/studies/smoke/plan.json"
STUDIES = ("smoke", "pilot", "e1", "e4")
Commit = Callable[[Path, str], str]


def unamended(plan: Plan) -> Plan:
    """``plan`` without its amendments and the runs they added: the plan as it was."""
    added = {amendment.run_id for amendment in plan.amendments}
    runs = [run for run in plan.runs if run.run_id not in added]
    return dataclasses.replace(plan, runs=runs, amendments=())


@pytest.fixture
def checkout(git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A SYNTHETIC scratch checkout holding copies of one REAL task and its smoke run.

    The smoke run was made before the canary (DECISIONS D52), so the copy of its task
    has the canary taken out again: the task files exactly as the run recorded them.
    """
    task = git_repo / "bench" / "tasks" / TASK
    shutil.copytree(ROOT / "bench" / "tasks" / TASK, task)
    remove_canary(task)
    record = json.loads((REAL_RUN / "run.json").read_text(encoding="utf-8"))
    assert tree_sha256(task) == record["provenance"]["task_tree_sha256"]
    for study in STUDIES:
        shutil.copytree(REAL_RUN, git_repo / "artifacts" / "studies" / study / "runs" / RUN_ID)
    # The REAL smoke plan as it was before any amendment (read only), which plans the
    # REAL run copied above; the tests amend their own copy, whether or not the real
    # plan has been amended since.
    write_plan(git_repo / SMOKE_PLAN, unamended(load_plan(ROOT / SMOKE_PLAN)))
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
        "verifier_mode": "task_requirements",
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


@pytest.mark.parametrize("mode", [None, "no_requirements"])
def test_a_held_out_evaluation_in_another_verifier_mode_is_refused(
    checkout: Path, capsys: pytest.CaptureFixture[str], mode: str | None
) -> None:
    # It did not evaluate the instrument (DECISIONS D54): no row is banked from it.
    path = seeded_eval(checkout)
    data = json.loads(path.read_text())
    if mode is None:
        del data["verifier_mode"]
    else:
        data["verifier_mode"] = mode
    path.write_text(json.dumps(data))
    for study in ("e1", "e4"):
        assert bank_study.main([study]) == 2
        assert "verifier mode" in capsys.readouterr().err
        assert not any(p.exists() for p in outputs(checkout, study))


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


# ---------------------------------------------------------------- smoke and the plan (D71)

EXCLUDED = "smoke-py-units-refactor-ma-qwen7b"
ADDED = f"{EXCLUDED}-ctx32k"


def amend_smoke_plan(root: Path) -> None:
    """Amend the scratch copy of the smoke plan as D71 does (a SYNTHETIC amendment here)."""
    path = root / SMOKE_PLAN
    amended = amend_plan(
        load_plan(path),
        EXCLUDED,
        ServerRequirement(min_n_ctx_per_slot=32768, max_parallel_slots=1),
        decision="D71",
        reason="SYNTHETIC test amendment",
        date="2026-11-12",
        plan_sha256_before=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    write_plan(path, amended)


def model_server(n_ctx: int, slots: int) -> dict[str, Any]:
    """The model server record tools/run_study.py writes for a server of the pinned 7B
    model with ``n_ctx`` tokens per slot on ``slots`` slots (nothing is served here)."""
    model = dataclasses.replace(QWEN_CODER_7B, n_ctx=n_ctx)
    record = dict(LocalServer(model, engine="llama.cpp", parallel=slots).provenance())
    record["n_ctx_per_slot_default"] = QWEN_CODER_7B.n_ctx
    record["n_ctx_per_slot_is_default"] = n_ctx == QWEN_CODER_7B.n_ctx
    return record


def stand_in(root: Path, run_id: str = ADDED, **provenance: Any) -> Path:
    """Bank a SYNTHETIC stand-in for the run the amendment added: only the run.json
    fields smoke banking reads, made as the amended plan plans it (no model ran). With
    the plan not amended, it stands in for a run that plan does not hold."""
    plan = load_plan(root / SMOKE_PLAN)
    planned = {run.run_id: run for run in plan.runs}
    spec = planned.get(run_id) or dataclasses.replace(planned[EXCLUDED], run_id=run_id)
    amendment = plan.amendment(run_id)
    prov: dict[str, Any] = {
        "run_spec": {**dataclasses.asdict(spec), "conditions": dict(spec.conditions)},
        "model_server": model_server(32768, 1),
        **({} if amendment is None else {"plan_amendment": amendment.to_json()}),
        **provenance,
    }
    record = {
        "run_id": run_id,
        "task_id": spec.task_id,
        "config_id": spec.config_id,
        "model": QWEN_CODER_7B.name,
        "stop_reason": "finished",
        "turns": 3,
        "provenance": prov,
    }
    run = root / "artifacts" / "studies" / "smoke" / "runs" / run_id
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return run


def test_smoke_banking_includes_the_run_a_plan_amendment_added(checkout: Path) -> None:
    amend_smoke_plan(checkout)
    stand_in(checkout)
    assert bank_study.main(["smoke"]) == 0
    smoke = json.loads((checkout / "artifacts" / "bench" / "smoke_runs.json").read_text())
    rows = {row["run_id"]: row for row in smoke["runs"]}
    assert sorted(rows) == sorted([RUN_ID, ADDED])
    assert rows[ADDED]["task_id"] == "py-units-refactor"
    assert rows[ADDED]["agent"] == f"minimal-agent/{QWEN_CODER_7B.name}"
    assert rows[ADDED]["synthetic"] is False  # the shape a real run would have; test-only
    plan_bytes = (checkout / SMOKE_PLAN).read_bytes()
    assert smoke["provenance"]["plan_sha256"] == hashlib.sha256(plan_bytes).hexdigest()
    assert smoke["failures"] is None  # no failure log in this scratch checkout


def bank_excluded_run(root: Path) -> None:
    """A SYNTHETIC run banked under the id the amendment replaced."""
    stand_in(root, EXCLUDED, model_server=model_server(16384, 4))


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        pytest.param(lambda root: stand_in(root), "not a planned run", id="unamended-plan"),
        pytest.param(
            lambda root: (
                amend_smoke_plan(root),
                stand_in(root, model_server=model_server(16384, 4)),
            ),
            "at least 32768 tokens per slot",
            id="smaller-window",
        ),
        pytest.param(
            lambda root: (amend_smoke_plan(root), stand_in(root, plan_amendment=None)),
            "plan amendment",
            id="no-amendment-record",
        ),
        pytest.param(
            lambda root: (amend_smoke_plan(root), bank_excluded_run(root)),
            "stays excluded",
            id="excluded-run-banked",
        ),
        pytest.param(
            lambda root: (root / SMOKE_PLAN).unlink(), "smoke/plan.json is missing", id="no-plan"
        ),
    ],
)
def test_smoke_banking_refuses_a_run_not_made_as_planned(
    checkout: Path, capsys: pytest.CaptureFixture[str], setup: Any, message: str
) -> None:
    setup(checkout)
    assert bank_study.main(["smoke"]) == 2
    err = capsys.readouterr().err
    assert "bank_study smoke: refused:" in err and message in err
    assert not (checkout / "artifacts" / "bench" / "smoke_runs.json").exists()
    assert not (checkout / "artifacts" / "studies" / "smoke" / "failures.jsonl").exists()


def test_smoke_banking_banks_the_failure_log_without_traces(checkout: Path) -> None:
    log = checkout / "runs" / "smoke" / "failures.jsonl"
    log.parent.mkdir(parents=True)
    entries = [
        {"run_id": EXCLUDED, "attempt": n, "started": "s", "time": "t", "error": "E", "trace": "T"}
        for n in (1, 2, 3)
    ]
    log.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    source = log.read_bytes()
    for _ in range(2):  # banking again adds nothing it holds already
        assert bank_study.main(["smoke"]) == 0
    banked = (checkout / "artifacts" / "studies" / "smoke" / "failures.jsonl").read_text()
    assert [json.loads(line) for line in banked.splitlines()] == [
        {k: v for k, v in e.items() if k != "trace"} for e in entries
    ]
    smoke = json.loads((checkout / "artifacts" / "bench" / "smoke_runs.json").read_text())
    assert smoke["failures"]["entries"] == 3 and smoke["failures"]["added"] == 0
    assert smoke["failures"]["sha256"] == hashlib.sha256(banked.encode()).hexdigest()
    assert log.read_bytes() == source  # the log itself is only read


# ---------------------------------------------------------------- --check (DECISIONS D57)


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def test_check_accepts_the_rows_banking_wrote_and_writes_nothing(
    checkout: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    for study in ("e1", "e4"):
        assert bank_study.main([study]) == 0
    # A later commit: the banking commit the rows record is no longer HEAD.
    commit(checkout, "SYNTHETIC banked rows")
    capsys.readouterr()
    written = [p for study in ("e1", "e4") for p in outputs(checkout, study) if p.exists()]
    before = {p: p.read_bytes() for p in written}
    for study in ("e1", "e4"):
        assert bank_study.main([study, "--check"]) == 0
    assert {p: p.read_bytes() for p in written} == before
    out = capsys.readouterr().out
    assert "e1: the 1 row(s) of artifacts/e1/runs.jsonl are the rows banking writes" in out
    assert "e4: the 1 row(s) of artifacts/e4/runs.jsonl are the rows banking writes" in out


def flip_verdict(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claim = rows[0]["claims"][0]
    claim["verdict"] = "supported" if claim["verdict"] == "contradicted" else "contradicted"
    return rows


def flip_truth(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows[0]["ground_truth_success"] = not rows[0]["ground_truth_success"]
    return rows


def flip_false_success(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows[0]["false_success"] = not rows[0]["false_success"]
    return rows


def other_trees(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows[0]["instrument"]["trees"] = {p: "e" * 40 for p in rescore.INSTRUMENT_RECORD_PATHS}
    return rows


def another_run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [*rows, dict(rows[0], run_id="e1-SYNTHETIC-not-banked")]


def spoofed_trees(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Other instrument trees, with a top-level key spelled like the flattened field and
    # holding the true trees, which once overwrote the nested field in the comparison.
    true_trees = rows[0]["instrument"]["trees"]
    rows[0]["instrument"]["trees"] = {p: "e" * 40 for p in rescore.INSTRUMENT_RECORD_PATHS}
    rows[0]["instrument.trees"] = true_trees
    return rows


@pytest.mark.parametrize(
    ("edit", "found"),
    [
        pytest.param(
            flip_verdict, "differ from the rows banking writes now in claims", id="verdict"
        ),
        pytest.param(flip_truth, "ground_truth_success", id="ground-truth"),
        pytest.param(flip_false_success, "false_success", id="false-success"),
        pytest.param(other_trees, "instrument.trees", id="instrument"),
        pytest.param(spoofed_trees, "instrument.trees", id="a-key-spelled-like-a-nested-field"),
        pytest.param(
            lambda rows: [], "1 banked run(s) have no row", id="a-banked-run-without-a-row"
        ),
        pytest.param(another_run, "1 row(s) have no banked run", id="a-row-without-a-banked-run"),
        pytest.param(lambda rows: rows + rows, "repeat", id="a-repeated-row"),
    ],
)
def test_check_finds_rows_that_are_not_the_banking(
    checkout: Path,
    capsys: pytest.CaptureFixture[str],
    edit: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    found: str,
) -> None:
    assert bank_study.main(["e1"]) == 0
    path = checkout / "artifacts" / "e1" / "runs.jsonl"
    rows = read_rows(path)
    assert rows[0]["claims"], "the REAL run's report has claims to flip"
    write_rows(path, edit(rows))
    capsys.readouterr()
    assert bank_study.main(["e1", "--check"]) == 1
    err = capsys.readouterr().err
    assert "bank_study e1 --check:" in err and found in err


def test_check_without_banked_rows_fails(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bank_study.main(["e4", "--check"]) == 1
    assert "artifacts/e4/runs.jsonl is missing" in capsys.readouterr().err
    assert not any(p.exists() for p in outputs(checkout, "e4"))


def test_check_of_a_malformed_rows_file_fails(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bank_study.main(["e1"]) == 0
    path = checkout / "artifacts" / "e1" / "runs.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "[1]\n{\n", encoding="utf-8")
    assert bank_study.main(["e1", "--check"]) == 1
    err = capsys.readouterr().err
    assert "artifacts/e1/runs.jsonl:2 is not a row" in err
    assert "artifacts/e1/runs.jsonl:3 is not JSON" in err


def test_check_refuses_uncommitted_code(checkout: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bank_study.main(["e1"]) == 0
    extra = checkout / "src" / "receipts" / "verify" / "extra.py"
    extra.parent.mkdir(parents=True)
    extra.write_text("SYNTHETIC = True\n")
    assert bank_study.main(["e1", "--check"]) == 2
    assert "src/receipts/verify/extra.py" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["e1", "--check", "--allow-dirty"], "--check re-derives the rows from committed code"),
        (["smoke", "--check"], "--check applies to e1 and e4 only"),
        (["pilot", "--check"], "--check applies to e1 and e4 only"),
    ],
)
def test_check_takes_only_the_rescored_studies_and_committed_code(
    argv: list[str], said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        bank_study.main(argv)
    assert said in capsys.readouterr().err
