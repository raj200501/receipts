"""Tests for tools/analyze.py, the command that runs the E1 and E2 analysis.

Every input here is SYNTHETIC and lives in tmp_path: rows from the generators of
tests/study/test_results.py, a SYNTHETIC G5 evaluation, plan, preregistration, failure
log, task directories, banked run records, banking record, and ledgers. Nothing computed
here is a study result. Some tests mark SYNTHETIC rows ``synthetic: False`` only to
exercise the confirmatory path, the G7 gate, and the preregistration check in a scratch
repository, into which they copy this repository's analysis code (the code that runs);
they never touch the real artifacts. Some tests read this repository's task directories
and import its banking tool in a subprocess, read-only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest

import analyze
import prereg
import ship_check
from gitutil import git
from receipts.bench.hashing import tree_sha256
from receipts.ledger.events import LedgerWriter
from receipts.study import rescore, results
from receipts.study.aggregate import e1_rows, write_jsonl
from tests.repo_tools.test_ship_check_g7 import REDERIVED, derived_ok, given, hidden_checks
from tests.study.test_results import (
    FREEZE_SHA,
    INSTRUMENT,
    failure,
    fast_cluster_bootstrap,
    g8_contradicted,
    ledger_events,
    record_of,
    strict_loads,
    synthetic_plan,
    synthetic_plan_object,
    synthetic_runs,
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


def write_tasks(root: Path, plan: dict[str, Any]) -> None:
    """SYNTHETIC task directories ``bench/tasks/<task_id>/`` for the plan's tasks."""
    for task in sorted({str(r["task_id"]) for r in plan["runs"]}):
        task_dir = root / analyze.TASKS / task
        (task_dir / "repo").mkdir(parents=True, exist_ok=True)
        (task_dir / "task.toml").write_text(f'id = "{task}"  # SYNTHETIC task\n', "utf-8")
        (task_dir / "repo" / "main.py").write_text("print('SYNTHETIC')\n", "utf-8")


def make_rows(
    root: Path,
    plan: dict[str, Any],
    *,
    synthetic: bool = True,
    silent: bool = True,
    commit: str = FREEZE_SHA,
    instrument_commit: str | None = None,
    no_results: bool = True,
) -> list[dict[str, Any]]:
    """SYNTHETIC rows of the plan's runs, each recording the code snapshot of ``commit``
    and the tree hash of its task directory under ``root``."""
    pairs = synthetic_runs(
        plan, synthetic=synthetic, silent=silent, commit=commit, no_results=no_results
    )
    for record, _ in pairs:
        task_dir = root / analyze.TASKS / record["task_id"]
        record["provenance"]["task_tree_sha256"] = tree_sha256(task_dir)
    return e1_rows(pairs, {**INSTRUMENT, "commit": instrument_commit or INSTRUMENT["commit"]})


def write_inputs(
    root: Path,
    *,
    synthetic: bool = True,
    silent: bool = True,
    with_plan: bool = True,
    plan_lines: bool = True,
    digest: Literal["file", "canonical"] = "file",
    with_rows: bool = True,
    evaluated: str | None = None,
) -> list[dict[str, Any]]:
    """Write SYNTHETIC E1 inputs under ``root`` and return the rows.

    The task directories, the held-out evaluation (whose instrument commit is
    ``evaluated`` when given), the plan, and the preregistration, which has
    ``planned_runs_per_config: 64`` and, when a plan is written, ``plan_sha256:`` with
    the plan file's SHA-256 (``digest="file"``) or the plan's canonical content hash
    ``Plan.sha256()`` (``digest="canonical"``, not accepted); ``plan_lines=False``
    leaves both lines out, as in the draft prereg 0001. The rows are written only when
    ``with_rows``.
    """
    plan = synthetic_plan()
    write_tasks(root, plan)
    seeded = synthetic_seeded()
    if evaluated is not None:
        seeded["instrument"]["commit"] = evaluated
    write_json(root / analyze.SEEDED, seeded)
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
    rows = make_rows(root, plan, synthetic=synthetic, silent=silent)
    if with_rows:
        write_jsonl(root / analyze.RUNS, rows)
    return rows


def copy_analysis_code(root: Path) -> None:
    """Copy every analysis code file that runs (``analyze.code_files``) to its path under
    ``root``, so that the code under --root is the code that runs."""
    for rel, path in analyze.code_files().items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


#: A SYNTHETIC line that makes a copied analysis code file differ from the one that runs.
EDIT = "# SYNTHETIC edit of a copied analysis code file\n"


def edit_code(root: Path, rel: str) -> str:
    """Append :data:`EDIT` to the copy of ``rel`` under ``root``; return its former text."""
    path = root / rel
    kept = path.read_text(encoding="utf-8")
    path.write_text(kept + EDIT, encoding="utf-8")
    return kept


def freeze_inputs(
    root: Path,
    commit: Commit,
    *,
    plan_lines: bool = True,
    digest: Literal["file", "canonical"] = "file",
    edited_at_freeze: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Commit and freeze a SYNTHETIC prereg, plan, evaluation, task files, and a copy of
    the analysis code in ``root``, then bank the rows; return them and the freeze commit.

    SYNTHETIC rows are marked ``synthetic: False`` only to exercise the confirmatory
    path in this scratch repository. The rows are banked after the freeze commit, as
    real data would be, and left uncommitted (:func:`bank`); they record the code
    snapshot of the freeze commit, the committed task files, and the evaluated
    instrument (banked at the freeze commit), and every included run has a hidden-check
    result. With ``edited_at_freeze``, the freeze commit holds that analysis code file
    with :data:`EDIT` added, and the file that runs is committed after the freeze.
    """
    write_tasks(root, synthetic_plan())
    copy_analysis_code(root)
    if edited_at_freeze is not None:
        edit_code(root, edited_at_freeze)
    base = commit(root, "SYNTHETIC task files and analysis code")
    options: dict[str, Any] = {"plan_lines": plan_lines, "digest": digest}
    write_inputs(root, synthetic=False, silent=False, with_rows=False, evaluated=base, **options)
    commit(root, "SYNTHETIC preregistration, plan, and held-out evaluation")
    prereg.freeze(root, results.PREREG_E1, "2026-11-04")
    frozen = commit(root, "freeze")
    if edited_at_freeze is not None:
        copy_analysis_code(root)
        commit(root, "SYNTHETIC analysis code changed after the freeze")
    rows = make_rows(
        root,
        synthetic_plan(),
        synthetic=False,
        silent=False,
        commit=frozen,
        instrument_commit=frozen,
        no_results=False,
    )
    bank(root, rows)
    return rows, frozen


def bank_runs(root: Path, rows: list[dict[str, Any]]) -> None:
    """Bank a SYNTHETIC run directory per row: run.json and ledger.jsonl.

    run.json is the record the row is the banking of (``record_of``: arm, model, family,
    conditions, seed, stop reason, turns, a report exactly when the row is included,
    ``synthetic``, and the provenance of its run code and task files), which ship_check
    g7 and the analysis compare with the row. The ledger opens with the run's
    run_start, holds one agent test run, shown in full or truncated (M2), from which E2
    classifies the run's contradicted claims, and ends with the run_end that carries
    the report the row was rescored from.
    """
    runs_dir = root / analyze.RUN_DIRS
    for r in rows:
        cut = r["conditions"]["M2"] == "truncated"
        shown = "....." if cut else "FAILED tests/test_a.py::t\n1 failed, 9 passed"
        record = record_of(r)
        events = ledger_events(
            r["run_id"],
            shown,
            cut,
            task_id=r["task_id"],
            config_id=r["config_id"],
            report=record["report"],
        )
        # The hidden-check result the row records, before the run_end, as the snapshot
        # writes it: gate G7 re-derives each row's ground truth from it (D57).
        events[-1:-1] = hidden_checks(r["ground_truth_success"])
        run_dir = runs_dir / r["run_id"]
        run_dir.mkdir(parents=True, exist_ok=True)
        writer = LedgerWriter(run_dir / "ledger.jsonl", clock=lambda: 1_700_000_000.0)
        for kind, data in events:
            writer.append(kind, data)
        write_json(run_dir / "run.json", record)


def write_banking(root: Path, banked_at: str) -> None:
    """The SYNTHETIC banking record of the rows file under ``root``, as
    ``tools/bank_study.py e1`` writes it: the rows file's SHA-256 and the commit
    ``banked_at`` the banking ran at."""
    write_json(
        root / analyze.ROWS_PROVENANCE,
        {
            "schema": "receipts.study.bank/1",
            "study": "e1",
            "rows": analyze.RUNS,
            "rows_sha256": sha256(root / analyze.RUNS),
            "runs_dir": analyze.RUN_DIRS,
            "provenance": {"git_sha": banked_at, "command": "SYNTHETIC", "study": "e1"},
        },
    )


def bank(root: Path, rows: list[dict[str, Any]]) -> None:
    """Bank SYNTHETIC rows as ``tools/bank_study.py e1`` leaves them: the rows file, a run
    directory per row (:func:`bank_runs`), and the banking record (:func:`write_banking`)
    at the commit the rows' instrument records."""
    write_jsonl(root / analyze.RUNS, rows)
    bank_runs(root, rows)
    write_banking(root, str(rows[0]["instrument"]["commit"]))


def stub_heavy_parts(monkeypatch: pytest.MonkeyPatch, *, exploratory: bool = False) -> None:
    """Replace the bootstraps (and, when asked, the exploratory models) by fast stand-ins.

    Tests of the run accounting and the provenance checks do not need them.
    """
    monkeypatch.setattr(results, "cluster_bootstrap", fast_cluster_bootstrap)
    monkeypatch.setattr(results, "bootstrap_coefficients", lambda *a, **k: {})
    if exploratory:
        stand_in = {"label": "EXPLORATORY", "note": "stubbed", "interactions": [], "skipped": []}
        monkeypatch.setattr(results, "exploratory_interactions", lambda *a, **k: stand_in)


def read_out(root: Path, rel: str) -> dict[str, Any]:
    """A strict JSON artifact written by the tool."""
    out: dict[str, Any] = strict_loads((root / rel).read_text(encoding="utf-8"))
    return out


def test_e1_writes_a_strict_synthetic_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_inputs(tmp_path)
    argv = ["e1", "--root", str(tmp_path), "--n-boot", "10"]
    assert analyze.main(argv) == 0
    out = read_out(tmp_path, analyze.E1_OUT)
    assert out["synthetic"] is True and out["confirmatory"] is False
    blockers = " | ".join(out["confirmatory_blockers"])
    assert "is not frozen" in blockers and "not a git repository" in blockers
    assert "n_boot=10" in blockers and "the input rows are synthetic" in blockers
    assert results.NO_FREEZE_COMMIT in out["confirmatory_blockers"]
    # tmp_path holds neither the analysis code that runs nor banked runs.
    assert "the analysis code that runs differs from the files under --root" in blockers
    assert "there is no banking record" in blockers and "have no banked run" in blockers
    assert out["banking"]["banking_record_found"] is False
    assert set(out["configs"]) == {"ma-qwen7b", "ma-qwen1.5b", "ma-granite8b", "ma-granite2b"}
    prov = out["provenance"]
    assert prov["command"] == "python tools/analyze.py " + " ".join(argv)
    assert prov["git_sha"].startswith("unknown") and prov["created"]
    for rel in (analyze.RUNS, analyze.SEEDED, analyze.PLAN, results.PREREG_E1):
        assert prov["inputs"][rel] == sha256(tmp_path / rel)
    assert analyze.FAILURES not in prov["inputs"]  # no failure log was banked
    assert out["runs"]["failure_log_entries"] is None
    assert out["instrument"]["seeded_eval_sha256"] == sha256(tmp_path / analyze.SEEDED)
    assert prov["prereg"] == out["prereg"] == results.PREREG_E1
    assert prov["prereg_sha256"] == out["prereg_sha256"] == sha256(tmp_path / results.PREREG_E1)
    for rel in (
        "tools/analyze.py",
        "src/receipts/study/results.py",
        "src/receipts/study/rescore.py",
    ):
        assert rel in prov["analysis_code"]
    assert {"python", "numpy", "scipy", "platform"} <= set(prov["environment"])
    printed = capsys.readouterr().out
    assert "e1: 4 configuration(s)" in printed and "not confirmatory:" in printed


def test_e1_confirmatory_artifact_passes_the_g7_gate_and_prereg_verify(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SYNTHETIC rows marked synthetic: False, only to exercise the confirmatory path in a
    # scratch repository; the bootstraps are replaced by a stand-in so that the
    # preregistered 2000 replicates stay fast. ship_check and prereg are the working-tree
    # versions that other agents are editing.
    stub_heavy_parts(monkeypatch)
    rows, frozen = freeze_inputs(git_repo, commit)
    assert analyze.freeze_commit(git_repo, results.PREREG_E1) == frozen
    assert analyze.main(["e1", "--root", str(git_repo)]) == 0
    out = read_out(git_repo, analyze.E1_OUT)
    assert out["confirmatory"] is True, out["confirmatory_blockers"]
    assert out["prereg_frozen"] is True and out["deviations"] == []
    assert out["banking"]["matches"] is True and out["banking"]["banked_runs"] == len(rows)
    inputs = out["provenance"]["inputs"]
    assert inputs[analyze.ROWS_PROVENANCE] == sha256(git_repo / analyze.ROWS_PROVENANCE)
    run_json = f"{analyze.RUN_DIRS}/{rows[0]['run_id']}/run.json"
    assert inputs[run_json] == sha256(git_repo / run_json)
    assert sum(name.endswith("/run.json") for name in inputs) == len(rows)
    assert out["plan_sha256_matches_prereg"] is True
    assert out["plan_sha256"] == sha256(git_repo / analyze.PLAN)
    assert out["plan_canonical_sha256"] == synthetic_plan_object().sha256()
    recorded = f"plan_sha256: {out['plan_sha256']}\n"
    assert recorded in (git_repo / results.PREREG_E1).read_text("utf-8")
    assert out["run_provenance"]["freeze_commit"] == frozen
    assert out["run_provenance"]["code"]["freeze_snapshot"] == len(rows)
    assert out["instrument"]["rows"]["trees_match_evaluation"] is True
    assert out["instrument"]["seeded_eval_sha256"] == sha256(git_repo / analyze.SEEDED)
    commit(git_repo, "SYNTHETIC E1 rows, runs, and results")
    ctx = ship_check.Context(
        orig=git_repo, clone=git_repo, logs=git_repo / "logs", fast=True, sha="0" * 40
    )
    # The scratch repository holds no project for make setup, tools/bank_study.py e1
    # --check, and the re-derivation of the results to run in, so their outcomes are
    # given as the G7 tests give them; those tests exercise the steps themselves (D57,
    # D65). The results here came from bootstrap stand-ins (stub_heavy_parts) and record
    # --root, so a fresh derivation would differ: tests/report/test_derived.py runs the
    # real one on results that tools/analyze.py wrote from the repository root.
    ctx.results["make-setup"] = given("make-setup")
    ctx.results["bank-check-e1"] = given("bank-check-e1", stdout=REDERIVED)
    rel = analyze.E1_OUT
    ctx.results[f"derived-{rel}"] = derived_ok(rel, "python tools/analyze.py e1")
    assert "4 configs, 2 families" in ship_check.g7(ctx)
    verified = prereg.verify(git_repo)
    assert verified.ok, verified.problems
    assert verified.confirmatory_artifacts == [analyze.E1_OUT]


def test_a_prereg_recording_the_canonical_plan_digest_is_not_confirmatory(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The canonical content hash Plan.sha256() is no longer accepted as plan_sha256.
    stub_heavy_parts(monkeypatch, exploratory=True)
    freeze_inputs(git_repo, commit, digest="canonical")
    assert analyze.main(["e1", "--root", str(git_repo)]) == 0
    out = read_out(git_repo, analyze.E1_OUT)
    assert out["confirmatory"] is False and out["plan_sha256_matches_prereg"] is False
    (blocker,) = out["confirmatory_blockers"]
    assert "canonical content SHA-256" in blocker and "not accepted" in blocker


def test_a_frozen_prereg_without_its_plan_lines_blocks_e1_and_e2(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A SYNTHETIC prereg frozen without planned_runs_per_config and plan_sha256 lines
    # (as the draft prereg 0001 stands): neither the sample size nor the plan is tied to
    # it, so neither artifact may be confirmatory. Bootstraps are stubbed for speed.
    stub_heavy_parts(monkeypatch, exploratory=True)
    freeze_inputs(git_repo, commit, plan_lines=False)
    assert analyze.prereg_status(git_repo, results.PREREG_E1).frozen
    expected = [results.MISSING_PLANNED_RUNS, results.MISSING_PLAN_DIGEST]
    assert analyze.main(["e1", "--root", str(git_repo)]) == 0
    e1 = read_out(git_repo, analyze.E1_OUT)
    assert e1["prereg_frozen"] is True and e1["confirmatory"] is False
    assert e1["confirmatory_blockers"] == expected
    assert e1["plan_sha256_matches_prereg"] is None
    assert analyze.main(["e2", "--root", str(git_repo)]) == 0
    e2 = read_out(git_repo, analyze.E2_OUT)
    assert e2["prereg_frozen"] is True and e2["confirmatory"] is False
    assert e2["confirmatory_blockers"] == expected


def test_e2_applies_the_analysis_code_checks(git_repo: Path, commit: Commit) -> None:
    # SYNTHETIC rows marked synthetic: False, only to exercise E2's confirmatory path.
    _, frozen = freeze_inputs(git_repo, commit)
    argv = ["e2", "--root", str(git_repo)]

    def run() -> dict[str, Any]:
        assert analyze.main(argv) == 0
        return read_out(git_repo, analyze.E2_OUT)

    clean = run()
    assert clean["confirmatory"] is True, clean["confirmatory_blockers"]
    assert clean["deviations"] == [] and clean["plan_sha256_matches_prereg"] is True
    assert clean["run_provenance"]["freeze_commit"] == frozen
    assert clean["banking"]["matches"] is True
    rel = "src/receipts/study/results.py"
    edit_code(git_repo, rel)
    dirty = run()
    assert dirty["confirmatory"] is False
    differs, uncommitted = dirty["confirmatory_blockers"]
    assert "the analysis code that runs differs from the files under --root" in differs
    assert differs.endswith(f": {rel}")
    assert "uncommitted changes" in uncommitted and rel in uncommitted
    assert dirty["provenance"]["uncommitted_analysis_code"] == [rel]
    # The edit committed: --root is a clean checkout now, but its analysis code is not
    # the code that runs, so the commit checks would describe other code (finding 2).
    commit(git_repo, "SYNTHETIC change of the analysis code after the freeze")
    committed = run()
    assert committed["confirmatory"] is False
    (blocker,) = committed["confirmatory_blockers"]
    assert "differs from the files under --root" in blocker and blocker.endswith(f": {rel}")
    assert committed["provenance"]["uncommitted_analysis_code"] == []
    (deviation,) = committed["deviations"]
    assert deviation["kind"] == "analysis_code_changed" and deviation["files"] == [rel]


def test_analysis_code_changed_after_the_freeze_is_a_deviation(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SYNTHETIC: the freeze commit holds another version of results.py than the one that
    # runs, which is committed after the freeze. The artifact stays confirmatory and lists
    # the change (section 5).
    stub_heavy_parts(monkeypatch, exploratory=True)
    rel = "src/receipts/study/results.py"
    freeze_inputs(git_repo, commit, edited_at_freeze=rel)
    for command, out_rel in (("e1", analyze.E1_OUT), ("e2", analyze.E2_OUT)):
        assert analyze.main([command, "--root", str(git_repo)]) == 0
        out = read_out(git_repo, out_rel)
        assert out["confirmatory"] is True, out["confirmatory_blockers"]
        (deviation,) = [d for d in out["deviations"] if d["kind"] == "analysis_code_changed"]
        assert (deviation["stage"], deviation["files"]) == ("analysis", [rel])
        assert rel in deviation["detail"] and deviation["prereg_section"] == "5"


def test_banking_code_changed_at_the_banking_commit_is_a_deviation(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SYNTHETIC history (finding 7): the freeze F; a commit B whose rescoring code differs
    # from F's, where the runs are banked; a commit A that restores F's code, where the
    # analysis runs. A holds the code of the freeze commit, yet every outcome came from
    # B's code, so the change is reported with the banking commit.
    stub_heavy_parts(monkeypatch, exploratory=True)
    rows, frozen = freeze_inputs(git_repo, commit)
    rel = "src/receipts/study/rescore.py"
    kept = edit_code(git_repo, rel)
    banked_at = commit(git_repo, "SYNTHETIC change of the rescoring; the runs are banked here")
    bank(git_repo, [{**r, "instrument": {**r["instrument"], "commit": banked_at}} for r in rows])
    (git_repo / rel).write_text(kept, encoding="utf-8")
    commit(git_repo, "SYNTHETIC rescoring restored to the code of the freeze commit")
    for command, out_rel in (("e1", analyze.E1_OUT), ("e2", analyze.E2_OUT)):
        assert analyze.main([command, "--root", str(git_repo)]) == 0
        out = read_out(git_repo, out_rel)
        assert out["confirmatory"] is True, out["confirmatory_blockers"]
        (deviation,) = [d for d in out["deviations"] if d["kind"] == "analysis_code_changed"]
        assert (deviation["stage"], deviation["banking_commit"]) == ("banking", banked_at)
        assert deviation["files"] == [rel] and frozen[:12] in deviation["detail"]
    # Rows that name a banking commit this repository does not hold cannot be checked.
    unknown = "9" * 40
    bank(git_repo, [{**r, "instrument": {**r["instrument"], "commit": unknown}} for r in rows])
    assert analyze.main(["e2", "--root", str(git_repo)]) == 0
    out = read_out(git_repo, analyze.E2_OUT)
    assert out["confirmatory"] is False
    (blocker,) = out["confirmatory_blockers"]
    assert unknown in blocker and "not a commit of this repository" in blocker


def test_a_task_changed_after_the_freeze_blocks_e1_and_e2(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SYNTHETIC: a task edited and committed after the freeze; its runs recorded the new
    # files (as banking requires), which are not the files frozen with the prereg.
    stub_heavy_parts(monkeypatch, exploratory=True)
    rows, _ = freeze_inputs(git_repo, commit)
    task = str(rows[0]["task_id"])
    (git_repo / analyze.TASKS / task / "task.toml").write_text("# SYNTHETIC edit\n", "utf-8")
    commit(git_repo, "SYNTHETIC task edit after the freeze")
    now = tree_sha256(git_repo / analyze.TASKS / task)
    changed = [{**r, "task_tree_sha256": now} if r["task_id"] == task else r for r in rows]
    bank(git_repo, changed)
    affected = sorted(str(r["run_id"]) for r in changed if r["task_id"] == task)
    for command, rel in (("e1", analyze.E1_OUT), ("e2", analyze.E2_OUT)):
        assert analyze.main([command, "--root", str(git_repo)]) == 0
        out = read_out(git_repo, rel)
        assert out["confirmatory"] is False
        (blocker,) = out["confirmatory_blockers"]
        assert "differ from the task files at the freeze commit" in blocker
        deviation = next(d for d in out["deviations"] if d["kind"] == "task_files_changed")
        assert deviation["run_ids"] == affected and set(deviation["tasks"]) == {task}
        assert deviation["tasks"][task]["recorded"] == [now]


def test_e1_lists_excluded_runs_from_the_banked_failure_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_heavy_parts(monkeypatch, exploratory=True)
    rows = write_inputs(tmp_path)
    write_jsonl(tmp_path / analyze.RUNS, rows[:-1])
    gone = str(rows[-1]["run_id"])
    log = [failure(gone, n, f"OSError {n}") for n in (1, 2, 3)]
    path = tmp_path / analyze.FAILURES
    path.write_text("".join(json.dumps(e) + "\n" for e in log), encoding="utf-8")
    assert analyze.main(["e1", "--root", str(tmp_path), "--n-boot", "5"]) == 0
    out = read_out(tmp_path, analyze.E1_OUT)
    runs = out["runs"]
    assert runs["missing_run_ids"] == runs["excluded_run_ids"] == [gone]
    assert runs["not_executed_run_ids"] == [] and runs["failure_log_entries"] == 3
    (excluded,) = runs["excluded"]
    assert [e["error"] for e in excluded["errors"]] == [f"SYNTHETIC OSError {n}" for n in (1, 2, 3)]
    assert all("trace" not in e for e in excluded["errors"])
    assert out["provenance"]["inputs"][analyze.FAILURES] == sha256(path)
    path.write_text('{"attempt": 1}\n', encoding="utf-8")
    assert analyze.main(["e1", "--root", str(tmp_path), "--n-boot", "5"]) == 2
    assert "has no run_id" in capsys.readouterr().err


def test_rows_must_be_the_banking_of_exactly_the_banked_runs(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SYNTHETIC rows marked synthetic: False, only to exercise the confirmatory path
    # (finding 1): each way the rows can fail to be the banking of the banked runs.
    stub_heavy_parts(monkeypatch, exploratory=True)
    rows, frozen = freeze_inputs(git_repo, commit)

    def blockers(command: str = "e2") -> list[str]:
        assert analyze.main([command, "--root", str(git_repo)]) == 0
        found: list[str] = read_out(
            git_repo, analyze.E1_OUT if command == "e1" else analyze.E2_OUT
        )["confirmatory_blockers"]
        return found

    assert blockers() == []
    # A stale runs.jsonl, with a banking record of that stale file: banked runs without a
    # row are blocked, and the run accounting does not count them as never executed.
    dropped = sorted(
        str(r["run_id"]) for r in rows if r["config_id"] == "ma-qwen1.5b" and r["false_success"]
    )
    assert dropped
    write_jsonl(git_repo / analyze.RUNS, [r for r in rows if str(r["run_id"]) not in dropped])
    write_banking(git_repo, frozen)
    (stale,) = blockers("e1")
    assert f"{len(dropped)} banked run(s)" in stale and "have no row" in stale
    e1 = read_out(git_repo, analyze.E1_OUT)
    assert e1["banking"]["banked_without_row_run_ids"] == dropped
    assert e1["runs"]["banked_without_row_run_ids"] == dropped == e1["runs"]["missing_run_ids"]
    assert e1["runs"]["not_executed_run_ids"] == [] == e1["runs"]["excluded_run_ids"]
    assert blockers() == [stale]
    # The rows file changed after the banking, or no banking record at all.
    bank(git_repo, rows)
    write_jsonl(git_repo / analyze.RUNS, list(reversed(rows)))
    (changed,) = blockers()
    assert "is not the file the banking wrote" in changed
    (git_repo / analyze.ROWS_PROVENANCE).unlink()
    (absent,) = blockers()
    assert "there is no banking record" in absent
    # A banked run.json that differs from its row, and a row whose run is not banked (one
    # without contradicted claims, so E2 reads no ledger of it).
    bank(git_repo, rows)
    first = str(rows[0]["run_id"])
    second = next(
        str(r["run_id"])
        for r in rows[1:]
        if not any(c["verdict"] == "contradicted" for c in r["claims"])
    )
    path = git_repo / analyze.RUN_DIRS / first / "run.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    write_json(path, {**record, "seed": record["seed"] + 1})
    shutil.rmtree(git_repo / analyze.RUN_DIRS / second)
    unbanked, differing = blockers()
    assert "have no banked run" in unbanked and unbanked.endswith(f": {second}")
    assert "differ from their banked run.json in seed" in differing
    assert differing.endswith(f": {first}")
    # A run.json that records another run than its directory is a malformed input.
    write_json(path, {**record, "run_id": "e1-another-run"})
    assert analyze.main(["e2", "--root", str(git_repo)]) == 2


def test_inputs_read_from_other_paths_are_not_confirmatory(git_repo: Path, commit: Commit) -> None:
    # SYNTHETIC (finding 5): the same banked runs read from a copy give the same mix, but
    # section 5 defines the analysis with its default arguments.
    freeze_inputs(git_repo, commit)
    shutil.copytree(git_repo / analyze.RUN_DIRS, git_repo / "elsewhere" / "runs")
    assert analyze.main(["e2", "--root", str(git_repo), "--run-dirs", "elsewhere/runs"]) == 0
    out = read_out(git_repo, analyze.E2_OUT)
    assert out["confirmatory"] is False and out["banking"]["matches"] is True
    (blocker,) = out["confirmatory_blockers"]
    assert blocker.startswith("--run-dirs reads the banked runs from elsewhere/runs, not from")


def test_e1_without_a_plan(tmp_path: Path) -> None:
    write_inputs(tmp_path, with_plan=False)
    args = analyze.build_parser().parse_args(["e1", "--root", str(tmp_path)])
    rows, seeded, seeded_sha, info, plan, failures = analyze.load_e1_inputs(tmp_path, args)
    assert plan is None and failures is None and len(rows) == 4 * 64
    assert seeded["split"] == "heldout" and seeded_sha == sha256(tmp_path / analyze.SEEDED)
    assert info.planned_runs_per_config == 64 and not info.frozen


def test_e2_classifies_exactly_the_contradicted_claims(tmp_path: Path) -> None:
    rows = write_inputs(tmp_path)
    bank_runs(tmp_path, rows)
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 0
    out = read_out(tmp_path, analyze.E2_OUT)
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
    assert inputs[analyze.SEEDED] == sha256(tmp_path / analyze.SEEDED)
    some = out["claims"][0]["run_id"]
    ledger = f"{analyze.RUN_DIRS}/{some}/ledger.jsonl"
    assert inputs[ledger] == sha256(tmp_path / ledger)
    run_json = f"{analyze.RUN_DIRS}/{some}/run.json"
    assert inputs[run_json] == sha256(tmp_path / run_json)
    assert not any(name.endswith("verification.json") for name in inputs)
    assert out["banking"]["banked_runs"] == len(rows)
    assert out["banking"]["rows_differing_from_run_json"] == {}
    assert out["provenance"]["command"] == f"python tools/analyze.py e2 --root {tmp_path}"
    (tmp_path / analyze.PLAN).unlink()
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 0
    unplanned = read_out(tmp_path, analyze.E2_OUT)
    assert any("no study plan" in b for b in unplanned["confirmatory_blockers"])


def test_errors_exit_with_status_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 2
    assert "runs.jsonl" in capsys.readouterr().err
    rows = write_inputs(tmp_path)
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 2
    assert "is missing" in capsys.readouterr().err
    write_json(tmp_path / analyze.SEEDED, {**synthetic_seeded(), "split": "dev"})
    assert analyze.main(["e1", "--root", str(tmp_path), "--n-boot", "5"]) == 2
    assert "held-out split" in capsys.readouterr().err
    # Not made in the preregistered verifier mode (DECISIONS D54): no E1 artifact.
    write_json(tmp_path / analyze.SEEDED, {**synthetic_seeded(), "verifier_mode": None})
    assert analyze.main(["e1", "--root", str(tmp_path), "--n-boot", "5"]) == 2
    assert "verifier mode" in capsys.readouterr().err
    (tmp_path / analyze.SEEDED).write_text("[]", encoding="utf-8")
    assert analyze.main(["e1", "--root", str(tmp_path), "--n-boot", "5"]) == 2
    assert "is not a JSON object" in capsys.readouterr().err
    (tmp_path / analyze.SEEDED).write_text("{", encoding="utf-8")
    assert analyze.main(["e2", "--root", str(tmp_path)]) == 2
    assert "is not valid JSON" in capsys.readouterr().err
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
    assert analyze.read_failures(tmp_path, "absent.jsonl") is None


def test_load_seeded_digests_the_bytes_it_parses(tmp_path: Path) -> None:
    write_json(tmp_path / analyze.SEEDED, synthetic_seeded())
    data, digest = analyze.load_seeded(tmp_path, analyze.SEEDED)
    assert data == synthetic_seeded() and digest == sha256(tmp_path / analyze.SEEDED)
    (tmp_path / analyze.SEEDED).write_bytes(b"\xff")
    with pytest.raises(ValueError, match="is not valid JSON"):
        analyze.load_seeded(tmp_path, analyze.SEEDED)


def test_committed_tree_sha256_is_the_task_tree_hash_at_a_commit(
    git_repo: Path, commit: Commit
) -> None:
    # SYNTHETIC task files, with names whose order differs between path and string
    # sorting ("a-b/c" and "a/b"), a hidden file, and two files with the same bytes.
    task = git_repo / "bench" / "tasks" / "t1"
    files = {"a-b/c.txt": "1", "a/b.txt": "2", "a.txt": "3", "z/y/x.py": "4", ".hidden": "3"}
    for rel, text in files.items():
        (task / rel).parent.mkdir(parents=True, exist_ok=True)
        (task / rel).write_text(f"SYNTHETIC {text}\n", encoding="utf-8")
    (git_repo / "bench" / "tasks" / "t10").mkdir()
    (git_repo / "bench" / "tasks" / "t10" / "f.txt").write_text("SYNTHETIC t10\n", "utf-8")
    first = commit(git_repo, "SYNTHETIC tasks")
    frozen = tree_sha256(task)
    for rel in ("bench/tasks/t1", "bench/tasks/t1/"):
        assert analyze.committed_tree_sha256(git_repo, first, rel) == frozen
    other = analyze.committed_tree_sha256(git_repo, first, "bench/tasks/t10")
    assert other == tree_sha256(git_repo / "bench" / "tasks" / "t10") != frozen
    assert analyze.committed_tree_sha256(git_repo, first, "bench/tasks/absent") is None
    # A later edit, committed or not, leaves the hash at the first commit unchanged.
    (task / "a.txt").write_text("SYNTHETIC edited\n", encoding="utf-8")
    assert analyze.committed_tree_sha256(git_repo, first, "bench/tasks/t1") == frozen
    second = commit(git_repo, "SYNTHETIC edit")
    assert analyze.committed_tree_sha256(git_repo, second, "bench/tasks/t1") == tree_sha256(task)
    assert analyze.committed_tree_sha256(git_repo, first, "bench/tasks/t1") == frozen
    (task / "link").symlink_to("a.txt")
    third = commit(git_repo, "SYNTHETIC symbolic link")
    with pytest.raises(ValueError, match="symbolic link"):
        analyze.committed_tree_sha256(git_repo, third, "bench/tasks/t1")
    with pytest.raises(analyze.GitError):
        analyze.committed_tree_sha256(git_repo, "0" * 40, "bench/tasks/t1")
    with pytest.raises(analyze.GitError, match="not a readable blob"):
        analyze._blob_contents(git_repo, ["1" * 40])


def test_committed_tree_sha256_matches_run_study_on_a_real_task() -> None:
    # The hash of a clean task of this repository at HEAD is the hash tools/run_study.py
    # records for it from the checkout (read-only use of the real bench/tasks).
    root = analyze.ROOT
    for task_dir in sorted((root / analyze.TASKS).iterdir()):
        rel = f"{analyze.TASKS}/{task_dir.name}"
        status = git(root, "status", "--porcelain", "--ignored", "--untracked-files=all", "--", rel)
        if status.strip():
            continue
        assert analyze.committed_tree_sha256(root, "HEAD", rel) == tree_sha256(task_dir)
        return
    pytest.fail("no task directory of this repository is clean")


def test_freeze_state(git_repo: Path, commit: Commit) -> None:
    plan = synthetic_plan()
    write_tasks(git_repo, plan)
    (git_repo / "prereg").mkdir()
    (git_repo / results.PREREG_E1).write_text(PREREG_TEXT, encoding="utf-8")
    commit(git_repo, "SYNTHETIC tasks and draft")
    prereg.freeze(git_repo, results.PREREG_E1, "2026-11-04")
    frozen = commit(git_repo, "freeze")
    info = analyze.prereg_status(git_repo, results.PREREG_E1)
    asked = ["task00", "task01", "absent", "../tasks/task00", "", "task00"]
    state = analyze.freeze_state(git_repo, info, asked)
    tasks = git_repo / analyze.TASKS
    assert state.commit == frozen
    assert state.task_trees == {
        "": None,
        "../tasks/task00": None,
        "absent": None,
        "task00": tree_sha256(tasks / "task00"),
        "task01": tree_sha256(tasks / "task01"),
    }
    (tasks / "task00" / "task.toml").write_text("# SYNTHETIC edit\n", encoding="utf-8")
    commit(git_repo, "SYNTHETIC task edit after the freeze")
    later = analyze.freeze_state(git_repo, info, ["task00"])
    assert later.task_trees["task00"] == state.task_trees["task00"] != tree_sha256(tasks / "task00")
    draft = dataclasses.replace(info, frozen=False)
    assert analyze.freeze_state(git_repo, draft, ["task00"]) == results.FreezeState(None)


def test_input_checks(git_repo: Path, commit: Commit) -> None:
    write_json(git_repo / analyze.SEEDED, synthetic_seeded())
    commit(git_repo, "SYNTHETIC held-out evaluation")
    args = analyze.build_parser().parse_args(["e1", "--root", str(git_repo)])
    assert analyze.input_checks(git_repo, args) == []
    elsewhere = analyze.build_parser().parse_args(
        ["e2", "--root", str(git_repo), "--seeded", "x.json", "--failures", "y.jsonl"]
    )
    seeded, failures = analyze.input_checks(git_repo, elsewhere)
    assert "not from the held-out G5 evaluation" in seeded
    assert "not the banked artifacts/studies/e1/failures.jsonl" in failures
    # Section 5 fixes the other inputs to their default paths too (finding 5).
    paths = ["--runs", "r.jsonl", "--prereg", "p.md", "--plan", "x.json", "--run-dirs", "elsewhere"]
    moved = analyze.build_parser().parse_args(["e1", "--root", str(git_repo), *paths])
    found = analyze.input_checks(git_repo, moved)
    assert [b.split(" reads ")[0] for b in found] == ["--runs", "--prereg", "--plan", "--run-dirs"]
    assert found[0].startswith("--runs reads the rows from r.jsonl, not from artifacts/e1/")
    assert all(
        b.endswith("section 5 defines the analysis with its default arguments") for b in found
    )
    write_json(git_repo / analyze.SEEDED, {**synthetic_seeded(), "note": "SYNTHETIC edit"})
    (blocker,) = analyze.input_checks(git_repo, args)
    assert "has uncommitted changes" in blocker


#: How :func:`analyze.prereg_status` names files with uncommitted changes.
NOT_COMMITTED = ", so the frozen state read here is not the committed one"


def test_prereg_status(git_repo: Path, commit: Commit) -> None:
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    (git_repo / rel).write_text(PREREG_TEXT, encoding="utf-8")
    draft = analyze.prereg_status(git_repo, rel)
    assert not draft.frozen
    assert draft.problems == (
        f"{rel} is not in prereg/LOCK.json",
        f"uncommitted changes to {rel}{NOT_COMMITTED}",
    )
    assert draft.planned_runs_per_config == 64 and draft.plan_sha256 is None
    assert draft.sha256 == sha256(git_repo / rel)
    commit(git_repo, "draft")
    prereg.freeze(git_repo, rel, "2026-11-04")
    uncommitted = analyze.prereg_status(git_repo, rel)
    assert not uncommitted.frozen
    assert uncommitted.problems == (
        f"the prereg/LOCK.json entry for {rel} is not committed, so it is not frozen",
        f"uncommitted changes to prereg/LOCK.json{NOT_COMMITTED}",
    )
    commit(git_repo, "freeze")
    status = analyze.prereg_status(git_repo, rel)
    assert status.frozen and status.problems == ()
    (git_repo / rel).write_text("# E1 edited\n", encoding="utf-8")
    edited = analyze.prereg_status(git_repo, rel)
    assert not edited.frozen and "changed after it was frozen" in edited.problems[0]
    assert edited.problems[1] == f"uncommitted changes to {rel}{NOT_COMMITTED}"
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


def relock(root: Path, rel: str, text: str) -> None:
    """Write ``rel`` and a ``prereg/LOCK.json`` whose one entry records its SHA-256, with
    the hash chain recomputed (a SYNTHETIC edit of the frozen state that the working tree
    shows as consistent)."""
    (root / rel).write_text(text, encoding="utf-8")
    digest = sha256(root / rel)
    chained = prereg.entry_hash(prereg.GENESIS, rel, digest)
    prereg.write_lock(root, [prereg.LockEntry(rel, digest, prereg.GENESIS, chained, "2026-11-04")])


def test_an_edited_prereg_with_a_matching_lock_entry_is_not_frozen(
    git_repo: Path, commit: Commit
) -> None:
    # SYNTHETIC (finding 4): after the freeze, the prereg is edited together with its
    # LOCK.json entry and a recomputed chain, so the working tree is consistent.
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    relock(git_repo, rel, PREREG_TEXT)
    frozen = commit(git_repo, "SYNTHETIC freeze")
    assert analyze.prereg_status(git_repo, rel).frozen
    relock(git_repo, rel, PREREG_TEXT.replace("64", "80"))
    uncommitted = analyze.prereg_status(git_repo, rel)
    assert not uncommitted.frozen and uncommitted.planned_runs_per_config == 80
    at_freeze, at_head, dirty = uncommitted.problems
    assert f"committed at the freeze commit {frozen[:12]}" in at_freeze
    assert "edited after the freeze" in at_freeze
    assert at_head.startswith("the prereg/LOCK.json committed at HEAD does not list")
    assert dirty == f"uncommitted changes to {rel}, {prereg.LOCK}{NOT_COMMITTED}"
    # Committed, the edit is still not the frozen file: the freeze commit's entry decides.
    commit(git_repo, "SYNTHETIC edit of the frozen prereg and its lock entry")
    committed = analyze.prereg_status(git_repo, rel)
    (problem,) = committed.problems
    assert not committed.frozen and f"committed at the freeze commit {frozen[:12]}" in problem


def test_an_edit_hidden_from_git_status_is_not_frozen(git_repo: Path, commit: Commit) -> None:
    # SYNTHETIC: the edited prereg and lock entry are marked assume-unchanged, so git
    # status shows a clean tree; the lock entries committed at the freeze commit and at
    # HEAD still show that the file is not the frozen one.
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    relock(git_repo, rel, PREREG_TEXT)
    frozen = commit(git_repo, "SYNTHETIC freeze")
    relock(git_repo, rel, PREREG_TEXT + "SYNTHETIC hidden edit\n")
    git(git_repo, "update-index", "--assume-unchanged", rel, prereg.LOCK)
    assert analyze.uncommitted(git_repo, [rel, prereg.LOCK]) == []
    status = analyze.prereg_status(git_repo, rel)
    assert not status.frozen
    at_freeze, at_head = status.problems
    assert frozen[:12] in at_freeze and "committed at HEAD" in at_head


def test_lock_commit_reads_the_lock_history_in_topological_order(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    relock(git_repo, rel, PREREG_TEXT)
    frozen = commit(git_repo, "SYNTHETIC freeze")
    commit(git_repo, "SYNTHETIC later commit")
    calls: list[tuple[str, ...]] = []
    real = analyze.git

    def spy(root: Path, *args: str) -> str:
        calls.append(args)
        return real(root, *args)

    monkeypatch.setattr(analyze, "git", spy)
    assert analyze.lock_commit(git_repo, rel) == (frozen, sha256(git_repo / rel))
    (log,) = [args for args in calls if args[0] == "log"]
    assert "--reverse" in log and "--topo-order" in log
    assert analyze.lock_commit(git_repo, "prereg/0009-absent.md") is None
    assert analyze.lock_entry_at(git_repo, "HEAD", "prereg/0009-absent.md") is None
    assert analyze.lock_entry_at(git_repo, "0" * 40, rel) is None


def test_freeze_commit_outside_a_repository(tmp_path: Path) -> None:
    assert analyze.freeze_commit(tmp_path, results.PREREG_E1) is None


def test_code_checks(git_repo: Path, commit: Commit, tmp_path: Path) -> None:
    rel = results.PREREG_E1
    (git_repo / "prereg").mkdir()
    (git_repo / rel).write_text(PREREG_TEXT, encoding="utf-8")
    copy_analysis_code(git_repo)
    commit(git_repo, "SYNTHETIC draft and a copy of the analysis code")
    prereg.freeze(git_repo, rel, "2026-11-04")
    commit(git_repo, "freeze")
    info = analyze.prereg_status(git_repo, rel)
    assert info.frozen and analyze.code_checks(git_repo, info) == ([], [], [])
    kept = edit_code(git_repo, "tools/analyze.py")
    blockers, deviations, dirty = analyze.code_checks(git_repo, info)
    assert dirty == ["tools/analyze.py"] and deviations == []
    differs, uncommitted = blockers
    assert "differs from the files under --root" in differs
    assert "uncommitted changes" in uncommitted
    (git_repo / "tools" / "analyze.py").write_text(kept, encoding="utf-8")
    # A banking file the analysis does not import, committed after the freeze, is a
    # change of the analysis code too (finding 6).
    spec = git_repo / "src" / "receipts" / "bench" / "spec.py"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# SYNTHETIC task spec changed after the freeze\n", encoding="utf-8")
    commit(git_repo, "SYNTHETIC change of the task spec after the freeze")
    blockers, deviations, dirty = analyze.code_checks(git_repo, info)
    assert (blockers, dirty) == ([], [])
    (deviation,) = deviations
    assert deviation["kind"] == "analysis_code_changed" and deviation["stage"] == "analysis"
    assert deviation["files"] == ["src/receipts/bench/spec.py"]
    assert "src/receipts/bench/spec.py" in deviation["detail"]
    outside = analyze.code_checks(tmp_path, info)
    assert any("not a git repository" in b for b in outside[0])


def test_banking_code_checks(git_repo: Path, commit: Commit, tmp_path: Path) -> None:
    # SYNTHETIC history: the freeze, a commit that changes no banking code, and one that
    # changes the banking tool (and a bench file the banking never imports).
    tool = git_repo / "tools" / "bank_study.py"
    tool.parent.mkdir()
    tool.write_text("# SYNTHETIC banking tool v1\n", encoding="utf-8")
    other = git_repo / "src" / "receipts" / "bench" / "validate.py"
    other.parent.mkdir(parents=True)
    other.write_text("# SYNTHETIC v1\n", encoding="utf-8")
    frozen = commit(git_repo, "SYNTHETIC freeze")
    same = commit(git_repo, "SYNTHETIC commit without code changes")
    tool.write_text("# SYNTHETIC banking tool v2\n", encoding="utf-8")
    other.write_text("# SYNTHETIC v2\n", encoding="utf-8")
    changed = commit(git_repo, "SYNTHETIC change of the banking tool")
    leak = tmp_path / "leak.txt"
    banked_at = [same, changed, "9" * 40, f"--output={leak}"]
    blockers, deviations = analyze.banking_code_checks(git_repo, frozen, banked_at)
    (deviation,) = deviations
    assert (deviation["kind"], deviation["stage"]) == ("analysis_code_changed", "banking")
    assert deviation["banking_commit"] == changed and deviation["files"] == ["tools/bank_study.py"]
    unknown, not_an_id = blockers
    assert "9" * 40 in unknown and "not a commit of this repository" in unknown
    assert "--output=" in not_an_id
    assert not leak.exists()  # a banking commit that is not a commit id never reaches git
    assert analyze.banking_code_checks(git_repo, frozen, []) == ([], [])


def test_banking_commits() -> None:
    rows = [
        {"instrument": {"commit": "b" * 40}},
        {"instrument": {"commit": "b" * 40}},
        {"instrument": {"commit": ""}},
        {"instrument": None},
        {},
    ]
    banking = {"provenance": {"git_sha": "a" * 40}}
    assert analyze.banking_commits(rows, banking) == ["a" * 40, "b" * 40]
    assert analyze.banking_commits(rows, None) == ["b" * 40]
    assert analyze.banking_commits([], {"provenance": "SYNTHETIC"}) == []


def test_running_code_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (missing,) = analyze.running_code_problems(tmp_path)
    assert "differs from the files under --root" in missing
    assert ": src/receipts/analysis/__init__.py, " in missing and missing.endswith(", ...")
    copy_analysis_code(tmp_path)
    assert analyze.running_code_problems(tmp_path) == []
    rel = "src/receipts/analysis/glmm.py"
    edit_code(tmp_path, rel)
    (edited,) = analyze.running_code_problems(tmp_path)
    assert edited.endswith(f": {rel}")
    (tmp_path / rel).unlink()
    (removed,) = analyze.running_code_problems(tmp_path)
    assert removed.endswith(f": {rel}")
    # A module that runs from outside a src/ layout has no path under --root, even when
    # its absolute path names an existing file with the same bytes.
    copy_analysis_code(tmp_path)
    files = analyze.code_files()
    tool = files["tools/analyze.py"]
    monkeypatch.setattr(analyze, "code_files", lambda: {**files, tool.as_posix(): tool})
    (absolute,) = analyze.running_code_problems(tmp_path)
    assert absolute.endswith(f": {tool.as_posix()}")


def test_code_hashes_and_the_analysis_code_list() -> None:
    hashes = analyze.code_hashes()
    files = analyze.code_files()
    assert set(hashes) == set(files)
    for rel in (
        "tools/analyze.py",
        "src/receipts/study/results.py",
        "src/receipts/study/rescore.py",
        "src/receipts/analysis/glmm.py",
        "src/receipts/evaluation/mechanism.py",
        "src/receipts/ledger/events.py",
    ):
        assert hashes[rel] == sha256(analyze.ROOT / rel)
    # Every file that runs is analysis code, and the banking code is too (finding 6).
    for rel in files:
        assert any(rel == p or rel.startswith(p + "/") for p in analyze.ANALYSIS_CODE), rel
    assert set(analyze.BANKING_CODE) <= set(analyze.ANALYSIS_CODE)
    for rel in ("tools/bank_study.py", "src/receipts/bench/spec.py"):
        assert rel in analyze.ANALYSIS_CODE and rel in analyze.BANKING_CODE


def test_banking_code_covers_what_bank_study_imports_besides_the_instrument() -> None:
    # Read-only import of this repository's banking tool in a fresh interpreter. Every
    # receipts module it loads is the instrument (whose git trees the rows record), a
    # package __init__, banking code (BANKING_CODE), or a module of the agent drivers and
    # model client that receipts.study.spec imports for its agent configuration types,
    # which never computes a row.
    script = (
        "import json, sys; sys.path.insert(0, 'tools'); import bank_study; "
        "print(json.dumps(sorted(m.__file__ for n, m in list(sys.modules.items()) "
        "if n.startswith('receipts') and getattr(m, '__file__', None))))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=analyze.ROOT, capture_output=True, text=True, check=True
    )
    loaded = [
        Path(f).resolve().relative_to(analyze.ROOT).as_posix() for f in json.loads(proc.stdout)
    ]
    instrument = tuple(f"{path}/" for path in rescore.INSTRUMENT_RECORD_PATHS)
    agent_only = (
        "src/receipts/drivers/",
        "src/receipts/client/",
        "src/receipts/budget.py",
        "src/receipts/guard.py",
    )
    rest = sorted(
        rel
        for rel in loaded
        if not rel.startswith(instrument + agent_only) and not rel.endswith("/__init__.py")
    )
    assert rest == sorted(p for p in analyze.BANKING_CODE if p.startswith("src/"))
