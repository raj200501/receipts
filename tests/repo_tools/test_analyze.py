"""Tests for tools/analyze.py, the command that runs the E1 and E2 analysis.

Every input here is SYNTHETIC and lives in tmp_path: rows from the generators of
tests/study/test_results.py, a SYNTHETIC G5 evaluation, plan, preregistration, and
ledgers. Nothing computed here is a study result. One test marks SYNTHETIC rows
``synthetic: False`` only to exercise the confirmatory path, the G7 gate, and the
preregistration check in a scratch repository; it never touches the real artifacts.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest

import analyze
import prereg
import ship_check
from receipts.study import results
from receipts.study.aggregate import e1_rows, write_jsonl
from tests.study.test_results import (
    MODEL_OF,
    bank_run,
    fast_cluster_bootstrap,
    g8_contradicted,
    strict_loads,
    synthetic_plan,
    synthetic_plan_object,
    synthetic_records,
    synthetic_seeded,
)

Commit = Callable[[Path, str], str]
PREREG_TEXT = "# E1 (SYNTHETIC test preregistration)\nplanned_runs_per_config: 64\n"


def sha256(path: Path) -> str:
    """SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    """Write JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_inputs(
    root: Path,
    *,
    synthetic: bool = True,
    silent: bool = True,
    with_plan: bool = True,
    plan_lines: bool = True,
    digest: Literal["file", "canonical"] = "file",
) -> list[dict[str, Any]]:
    """Write SYNTHETIC E1 inputs under ``root`` and return the rows.

    The SYNTHETIC preregistration has ``planned_runs_per_config: 64`` and, when a plan
    is written, ``plan_sha256:`` with the plan file's SHA-256 (``digest="file"``) or the
    plan's canonical content hash ``Plan.sha256()`` (``digest="canonical"``);
    ``plan_lines=False`` leaves both lines out, as in the draft prereg 0001.
    """
    plan = synthetic_plan()
    rows = e1_rows(synthetic_records(plan, synthetic=synthetic, silent=silent))
    write_jsonl(root / analyze.RUNS, rows)
    write_json(root / analyze.SEEDED, synthetic_seeded())
    text = "# E1 (SYNTHETIC test preregistration)\n"
    if plan_lines:
        text += "planned_runs_per_config: 64\n"
    if with_plan:
        write_json(root / analyze.PLAN, plan)
        if plan_lines:
            recorded = (
                sha256(root / analyze.PLAN)
                if digest == "file"
                else synthetic_plan_object().sha256()
            )
            text += f"plan_sha256: {recorded}\n"
    (root / "prereg").mkdir(exist_ok=True)
    (root / results.PREREG_E1).write_text(text, encoding="utf-8")
    return rows


def freeze_inputs(
    root: Path,
    commit: Commit,
    *,
    plan_lines: bool = True,
    digest: Literal["file", "canonical"] = "file",
) -> list[dict[str, Any]]:
    """Commit and freeze a SYNTHETIC prereg and plan in ``root``, then write the rows.

    SYNTHETIC rows are marked ``synthetic: False`` only to exercise the confirmatory
    path in this scratch repository. The rows are written after the freeze commit, as
    real data would be; they are left uncommitted.
    """
    options: dict[str, Any] = {"plan_lines": plan_lines, "digest": digest}
    write_inputs(root, synthetic=False, silent=False, **options)
    (root / analyze.RUNS).unlink()
    commit(root, "SYNTHETIC preregistration and plan")
    prereg.freeze(root, results.PREREG_E1, "2026-11-04")
    commit(root, "freeze")
    return write_inputs(root, synthetic=False, silent=False, **options)


def bank_runs(root: Path, rows: list[dict[str, Any]], git_sha: str = "0" * 40) -> None:
    """Bank a SYNTHETIC run directory per row: run.json, ledger.jsonl, verification.json.

    run.json holds what ship_check g7 compares with the row (arm, family, conditions,
    seed, a report exactly when the row is included, ``synthetic``) and the commit the
    run was launched from (``git_sha``). The ledger opens with the run's run_start and
    holds one agent test run, shown in full or truncated (M2), from which E2 classifies
    the run's contradicted claims.
    """
    runs_dir = root / analyze.RUN_DIRS
    for r in rows:
        cut = r["conditions"]["M2"] == "truncated"
        shown = "....." if cut else "FAILED tests/test_a.py::t\n1 failed, 9 passed"
        labels = {c["claim_id"]: c["verdict"] for c in r["claims"]}
        run_dir = bank_run(
            runs_dir,
            r["run_id"],
            shown,
            cut,
            labels,
            task_id=r["task_id"],
            config_id=r["config_id"],
        )
        record = {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "config_id": r["config_id"],
            "model": MODEL_OF[r["config_id"]],
            "family": r["model_family"],
            "conditions": r["conditions"],
            "seed": r["seed"],
            "report": "SYNTHETIC report: all tests pass." if r["included"] else "",
            "synthetic": r["synthetic"],
            "provenance": {"git_sha": git_sha},
        }
        write_json(run_dir / "run.json", record)


def test_e1_writes_a_strict_synthetic_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_inputs(tmp_path)
    argv = ["e1", "--root", str(tmp_path), "--n-boot", "10"]
    assert analyze.main(argv) == 0
    out = strict_loads((tmp_path / analyze.E1_OUT).read_text(encoding="utf-8"))
    assert out["synthetic"] is True and out["confirmatory"] is False
    blockers = " | ".join(out["confirmatory_blockers"])
    assert "is not frozen" in blockers and "not a git repository" in blockers
    assert "n_boot=10" in blockers and "the input rows are synthetic" in blockers
    assert set(out["configs"]) == {"ma-qwen7b", "ma-qwen1.5b", "ma-granite8b", "ma-granite2b"}
    prov = out["provenance"]
    assert prov["command"] == "python tools/analyze.py " + " ".join(argv)
    assert prov["git_sha"].startswith("unknown") and prov["created"]
    for rel in (analyze.RUNS, analyze.SEEDED, analyze.PLAN, results.PREREG_E1):
        assert prov["inputs"][rel] == sha256(tmp_path / rel)
    assert prov["prereg"] == out["prereg"] == results.PREREG_E1
    assert prov["prereg_sha256"] == out["prereg_sha256"] == sha256(tmp_path / results.PREREG_E1)
    assert "tools/analyze.py" in prov["analysis_code"]
    assert "src/receipts/study/results.py" in prov["analysis_code"]
    assert {"python", "numpy", "scipy", "platform"} <= set(prov["environment"])
    printed = capsys.readouterr().out
    assert "e1: 4 configuration(s)" in printed and "not confirmatory:" in printed


@pytest.mark.parametrize("digest", ["file", "canonical"])
def test_e1_confirmatory_artifact_passes_the_g7_gate_and_prereg_verify(
    git_repo: Path,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
    digest: Literal["file", "canonical"],
) -> None:
    # SYNTHETIC rows marked synthetic: False, only to exercise the confirmatory path in a
    # scratch repository; the bootstraps are replaced by a stand-in so that the
    # preregistered 2000 replicates stay fast. The prereg records the plan by either of
    # the two digests the project uses. ship_check and prereg are the working-tree
    # versions that other agents are editing.
    monkeypatch.setattr(results, "cluster_bootstrap", fast_cluster_bootstrap)
    monkeypatch.setattr(results, "bootstrap_coefficients", lambda *a, **k: {})
    rows = freeze_inputs(git_repo, commit, digest=digest)
    frozen_at = analyze.freeze_commit(git_repo, results.PREREG_E1)
    assert frozen_at is not None
    bank_runs(git_repo, rows, git_sha=frozen_at)  # launched from the freeze commit
    assert analyze.main(["e1", "--root", str(git_repo)]) == 0
    out = strict_loads((git_repo / analyze.E1_OUT).read_text(encoding="utf-8"))
    assert out["confirmatory"] is True, out["confirmatory_blockers"]
    assert out["prereg_frozen"] is True and out["deviations"] == []
    assert out["plan_sha256_matches_prereg"] is True
    assert out["plan_sha256"] == sha256(git_repo / analyze.PLAN)
    assert out["plan_canonical_sha256"] == synthetic_plan_object().sha256()
    recorded = out["plan_sha256" if digest == "file" else "plan_canonical_sha256"]
    assert f"plan_sha256: {recorded}\n" in (git_repo / results.PREREG_E1).read_text("utf-8")
    commit(git_repo, "SYNTHETIC E1 rows, runs, and results")
    ctx = ship_check.Context(
        orig=git_repo, clone=git_repo, logs=git_repo / "logs", fast=True, sha="0" * 40
    )
    assert "4 configs, 2 families" in ship_check.g7(ctx)
    verified = prereg.verify(git_repo)
    assert verified.ok, verified.problems
    assert verified.confirmatory_artifacts == [analyze.E1_OUT]


def test_a_frozen_prereg_without_its_plan_lines_blocks_e1_and_e2(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A SYNTHETIC prereg frozen without planned_runs_per_config and plan_sha256 lines
    # (as the draft prereg 0001 stands): neither the sample size nor the plan is tied to
    # it, so neither artifact may be confirmatory. Bootstraps are stubbed for speed.
    monkeypatch.setattr(results, "cluster_bootstrap", fast_cluster_bootstrap)
    monkeypatch.setattr(results, "bootstrap_coefficients", lambda *a, **k: {})
    rows = freeze_inputs(git_repo, commit, plan_lines=False)
    bank_runs(git_repo, rows)
    assert analyze.prereg_status(git_repo, results.PREREG_E1).frozen
    expected = [results.MISSING_PLANNED_RUNS, results.MISSING_PLAN_DIGEST]
    assert analyze.main(["e1", "--root", str(git_repo)]) == 0
    e1 = strict_loads((git_repo / analyze.E1_OUT).read_text(encoding="utf-8"))
    assert e1["prereg_frozen"] is True and e1["confirmatory"] is False
    assert e1["confirmatory_blockers"] == expected
    assert e1["plan_sha256_matches_prereg"] is None
    assert analyze.main(["e2", "--root", str(git_repo)]) == 0
    e2 = strict_loads((git_repo / analyze.E2_OUT).read_text(encoding="utf-8"))
    assert e2["prereg_frozen"] is True and e2["confirmatory"] is False
    assert e2["confirmatory_blockers"] == expected


def test_e2_applies_the_analysis_code_checks(git_repo: Path, commit: Commit) -> None:
    # SYNTHETIC rows marked synthetic: False, only to exercise E2's confirmatory path.
    rows = freeze_inputs(git_repo, commit)
    bank_runs(git_repo, rows)
    argv = ["e2", "--root", str(git_repo)]

    def run() -> dict[str, Any]:
        assert analyze.main(argv) == 0
        out: dict[str, Any] = strict_loads((git_repo / analyze.E2_OUT).read_text("utf-8"))
        return out

    clean = run()
    assert clean["confirmatory"] is True, clean["confirmatory_blockers"]
    assert clean["deviations"] == [] and clean["plan_sha256_matches_prereg"] is True
    code = git_repo / "tools" / "analyze.py"
    code.parent.mkdir()
    code.write_text("# SYNTHETIC stand-in for the analysis code\n", encoding="utf-8")
    dirty = run()
    assert dirty["confirmatory"] is False
    (blocker,) = dirty["confirmatory_blockers"]
    assert "uncommitted changes" in blocker and "tools/analyze.py" in blocker
    assert dirty["provenance"]["uncommitted_analysis_code"] == ["tools/analyze.py"]
    commit(git_repo, "change the analysis code after the freeze")
    changed = run()
    assert changed["confirmatory"] is True, changed["confirmatory_blockers"]
    (deviation,) = changed["deviations"]
    assert deviation["kind"] == "analysis_code_changed"
    assert "tools/analyze.py" in deviation["detail"]


def test_e1_without_a_plan(tmp_path: Path) -> None:
    write_inputs(tmp_path, with_plan=False)
    rows, seeded, info, plan = analyze.load_e1_inputs(
        tmp_path, analyze.RUNS, analyze.SEEDED, analyze.PLAN, results.PREREG_E1
    )
    assert plan is None and len(rows) == 4 * 64 and seeded["split"] == "heldout"
    assert info.planned_runs_per_config == 64 and not info.frozen


def test_e2_classifies_exactly_the_contradicted_claims(tmp_path: Path) -> None:
    rows = write_inputs(tmp_path)
    bank_runs(tmp_path, rows)
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 0
    out = strict_loads((tmp_path / analyze.E2_OUT).read_text(encoding="utf-8"))
    assert {(c["run_id"], c["claim_id"]) for c in out["claims"]} == g8_contradicted(rows)
    assert set(out["classes"]) == ship_check.MECHANISM_CLASSES
    assert {c["class"] for c in out["claims"]} == set(out["classes"])
    assert out["synthetic"] is True and out["confirmatory"] is False
    blockers = out["confirmatory_blockers"]
    assert not any("plan" in b for b in blockers)
    assert "the input rows are synthetic" in blockers
    assert any("not a git repository" in b for b in blockers)
    assert out["mix"]["overall"]["n"] == len(out["claims"])
    inputs = out["provenance"]["inputs"]
    assert inputs[analyze.RUNS] == sha256(tmp_path / analyze.RUNS)
    assert inputs[analyze.PLAN] == sha256(tmp_path / analyze.PLAN)
    some = out["claims"][0]["run_id"]
    ledger = f"{analyze.RUN_DIRS}/{some}/ledger.jsonl"
    assert inputs[ledger] == sha256(tmp_path / ledger)
    assert out["provenance"]["command"] == f"python tools/analyze.py e2 --root {tmp_path}"
    (tmp_path / analyze.PLAN).unlink()
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 0
    unplanned = strict_loads((tmp_path / analyze.E2_OUT).read_text(encoding="utf-8"))
    assert any("no study plan" in b for b in unplanned["confirmatory_blockers"])


def test_errors_exit_with_status_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 2
    assert "runs.jsonl" in capsys.readouterr().err
    rows = write_inputs(tmp_path)
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 2
    assert "is missing" in capsys.readouterr().err
    write_json(tmp_path / analyze.SEEDED, {"split": "dev", "items": []})
    assert analyze.main(["e1", "--root", str(tmp_path), "--n-boot", "5"]) == 2
    assert "held-out split" in capsys.readouterr().err
    assert rows


def test_main_reads_sys_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["analyze.py", "e1", "--root", str(tmp_path)])
    assert analyze.main() == 2


def test_refuses_synthetic_artifacts_on_the_gate_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(analyze, "ROOT", tmp_path)
    rows = write_inputs(tmp_path)
    bank_runs(tmp_path, rows)
    for argv in (["e1", "--root", str(tmp_path), "--n-boot", "5"], ["e2", "--root", str(tmp_path)]):
        assert analyze.main(argv) == 2
        assert "refusing to write a synthetic artifact" in capsys.readouterr().err
    assert not (tmp_path / analyze.E1_OUT).exists() and not (tmp_path / analyze.E2_OUT).exists()


def test_read_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")
    assert analyze.read_jsonl(path) == [{"a": 1}, {"b": 2}]
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1 is not a JSON object"):
        analyze.read_jsonl(path)
    path.write_text("{\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1 is not valid JSON"):
        analyze.read_jsonl(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="is not a JSON object"):
        analyze.read_json(path)


def test_prereg_status(git_repo: Path, commit: Commit) -> None:
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    (git_repo / rel).write_text(PREREG_TEXT, encoding="utf-8")
    draft = analyze.prereg_status(git_repo, rel)
    assert not draft.frozen and draft.problems == (f"{rel} is not in prereg/LOCK.json",)
    assert draft.planned_runs_per_config == 64 and draft.plan_sha256 is None
    assert draft.sha256 == sha256(git_repo / rel)
    commit(git_repo, "draft")
    prereg.freeze(git_repo, rel, "2026-11-04")
    uncommitted = analyze.prereg_status(git_repo, rel)
    assert not uncommitted.frozen and "is not committed" in uncommitted.problems[0]
    commit(git_repo, "freeze")
    assert analyze.prereg_status(git_repo, rel).frozen
    (git_repo / rel).write_text("# E1 edited\n", encoding="utf-8")
    edited = analyze.prereg_status(git_repo, rel)
    assert not edited.frozen and "changed after it was frozen" in edited.problems[0]
    (git_repo / rel).write_text(PREREG_TEXT, encoding="utf-8")
    lock = git_repo / "prereg" / "LOCK.json"
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["entries"][0]["prev"] = "1" * 64
    lock.write_text(json.dumps(data), encoding="utf-8")
    broken = analyze.prereg_status(git_repo, rel)
    assert not broken.frozen and "hash chain is broken" in broken.problems[0]
    lock.write_text("not json", encoding="utf-8")
    unreadable = analyze.prereg_status(git_repo, rel)
    assert "is unreadable" in unreadable.problems[0]


def test_freeze_commit_outside_a_repository(tmp_path: Path) -> None:
    assert analyze.freeze_commit(tmp_path, results.PREREG_E1) is None


def test_code_checks(git_repo: Path, commit: Commit, tmp_path: Path) -> None:
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    (git_repo / rel).write_text(PREREG_TEXT, encoding="utf-8")
    code = git_repo / "tools" / "analyze.py"
    code.parent.mkdir()
    code.write_text("# v1\n", encoding="utf-8")
    commit(git_repo, "code and draft")
    prereg.freeze(git_repo, rel, "2026-11-04")
    commit(git_repo, "freeze")
    info = analyze.prereg_status(git_repo, rel)
    assert analyze.code_checks(git_repo, info) == ([], [], [])
    code.write_text("# v2\n", encoding="utf-8")
    blockers, deviations, dirty = analyze.code_checks(git_repo, info)
    assert dirty == ["tools/analyze.py"] and deviations == []
    assert "uncommitted changes" in blockers[0]
    commit(git_repo, "change the analysis after the freeze")
    blockers, deviations, dirty = analyze.code_checks(git_repo, info)
    assert (blockers, dirty) == ([], [])
    assert deviations[0]["kind"] == "analysis_code_changed"
    assert "tools/analyze.py" in deviations[0]["detail"]
    outside = analyze.code_checks(tmp_path, info)
    assert "not a git repository" in outside[0][0]


def test_code_hashes() -> None:
    hashes = analyze.code_hashes()
    for rel in (
        "tools/analyze.py",
        "src/receipts/study/results.py",
        "src/receipts/analysis/glmm.py",
        "src/receipts/evaluation/mechanism.py",
        "src/receipts/ledger/events.py",
    ):
        assert len(hashes[rel]) == 64
    assert analyze.display_path(Path("/elsewhere/x.py")) == "/elsewhere/x.py"
