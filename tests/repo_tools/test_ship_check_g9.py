"""Gate G9 of tools/ship_check.py on a synthetic E4 study and hook (H18, H28, H29,
review-1 and review-2 of the harness review round, the pre-freeze items: the
preregistration's plan lines and identical cells, both held-out task lists, and the
evaluated instrument of DECISIONS D42, and review B2 and N6 of the e4230cc review: rows
that cover every banked run, outcomes re-derived from the banked runs, and each run's
code commit, DECISIONS D57; and review B5 of the 02bc774 review: results that are what
tools/analyze_e4.py writes, DECISIONS D65).

Every preregistration, plan, instrument file, held-out evaluation, run row, ledger,
result, latency sample, hook module, and demo transcript here is SYNTHETIC, made up only
to exercise ``ship_check.g9`` in throwaway git repositories. E4 rows are marked
``synthetic: false`` only so the gate treats them as real runs, the arms' models are
stand-in names, the instrument files are stand-ins whose only role is to have git trees,
and the hidden-check results are made up; nothing here is a model result or a real-world
result. The demo script prints fixed text. The SYNTHETIC projects hold no study code for
``tools/bank_study.py e4 --check`` or the re-derivation of the results
(``python -m receipts.report.derived``) to run, so g9 is given those steps' outcomes
(:func:`project`), except in the tests that run a stand-in or the real re-derivation (on
the SYNTHETIC study of tests/report/studies.py, whose results tools/analyze_e4.py wrote).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.evaluation import e3
from receipts.ledger.events import GENESIS, Event
from receipts.study import results_e4
from receipts.study import spec as study_spec
from receipts.study.aggregate import e4_rows
from receipts.study.rescore import INSTRUMENT_RECORD_PATHS, Rescored
from receipts.study.results_e4 import outcome_rows
from tests.repo_tools.test_ship_check_g7 import derived_fails, derived_ok, run_for_real

Commit = Callable[[Path, str], str]
GateError = ship_check.GateError

PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
E1_TASKS = ("py-e1-alpha", "py-e1-beta")
E4_TASKS = ("py-e4-gamma", "py-e4-delta")
CONFIGS = ("ma-qwen7b", "ma-granite8b")
FAMILY = {"ma-qwen7b": "qwen", "ma-granite8b": "granite"}
MITIGATIONS = ("none", "honesty", "evidence", "hook")
BASE = {"M2": "full", "M3": "neutral", "M4": "short", "M5": "reliable"}
PER_CELL = 4  # two held-out tasks, each with an attainable and an unattainable triple
VALID = ("tests_pass",)  # the SYNTHETIC valid claim types (Z1)
PREREG = "prereg/0002-e4-mitigation.md"
PLAN = "artifacts/studies/e4/plan.json"
E1_PLAN = "artifacts/studies/e1/plan.json"
RUNS = "artifacts/e4/runs.jsonl"
RESULTS = "artifacts/e4/results.json"
SEEDED = "artifacts/e0/seeded_eval.json"
REPORT = "SYNTHETIC report: all tests pass."
DEMO_TEXT = "SYNTHETIC hook demo: 1 claim contradicted, report corrected\n"
DEMO_SCRIPT = '''"""SYNTHETIC hook demo for the tools/ship_check.py G9 tests."""

import sys
import time

time.sleep({sleep})
sys.stdout.write({text!r})
'''
MAKEFILE = "# SYNTHETIC test project for gate G9 (not a real project).\nsetup:\n\t@true\n"
PYPROJECT = """\
[project]
name = "synthetic-hook"
version = "0"
requires-python = ">=3.11"

[project.scripts]
receipts-hook = "{target}"
"""
HOOK_MODULE = '''"""SYNTHETIC stand-in for the receipts-hook entry point."""


def main() -> int:
    """Do nothing (SYNTHETIC)."""
    return 0
'''
HOOK_DOC = "# receipts-hook (SYNTHETIC)\n\n## Install\n\nRun `uv sync`, then add the hooks.\n"


def put(root: Path, rel: str, data: Any) -> None:
    """Write text, or JSON, creating parent directories."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def sha256(root: Path, rel: str) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def model_of(config_id: str) -> str:
    """The stand-in model name of a SYNTHETIC arm."""
    return f"stand-in-{config_id}"


def snapshot_of(sha: str) -> dict[str, Any]:
    """The code a SYNTHETIC run records: a snapshot of commit ``sha``, in the provenance
    keys ``tools/run_study.py`` writes."""
    return {"git_sha": sha, "code": "snapshot", "snapshot_of": sha}


# ---------------------------------------------------------------- the SYNTHETIC instrument


def trees_at(root: Path, sha: str) -> dict[str, str | None]:
    """The git tree of each instrument path at commit ``sha`` (None when absent)."""
    out: dict[str, str | None] = {}
    for rel in INSTRUMENT_RECORD_PATHS:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "-q", f"{sha}:{rel}"],
            capture_output=True,
            text=True,
            check=False,
        )
        out[rel] = proc.stdout.strip() if proc.returncode == 0 else None
    return out


def write_instrument(root: Path, version: str = "v1") -> None:
    """SYNTHETIC stand-in files under every instrument path (only their git trees matter)."""
    for rel in INSTRUMENT_RECORD_PATHS:
        put(root, f"{rel}/__init__.py", f'"""SYNTHETIC stand-in for {rel}, {version}."""\n')


def instrument_record(root: Path, sha: str) -> dict[str, Any]:
    """The banking checkout's instrument record at ``sha``, in the form
    ``receipts.study.rescore.instrument_record`` writes it."""
    return {
        "commit": sha,
        "paths": list(INSTRUMENT_RECORD_PATHS),
        "trees": trees_at(root, sha),
        "dirty": False,
        "uncommitted": [],
    }


def seeded_eval(root: Path, sha: str) -> dict[str, Any]:
    """A SYNTHETIC held-out G5 evaluation of the instrument at ``sha``; g9 reads only its
    split, its verifier mode, and its instrument record."""
    return {
        "schema": "receipts.e0.seeded_eval/1",
        "split": "heldout",
        "synthetic_reports": True,
        "verifier_mode": "task_requirements",
        "items": [],
        "instrument": {**instrument_record(root, sha), "allow_dirty": False},
        "provenance": PROV,
    }


# ---------------------------------------------------------------- the SYNTHETIC study


def e4_plan(mitigations: tuple[str, ...] = MITIGATIONS) -> dict[str, Any]:
    """A SYNTHETIC E4 plan: every (configuration, mitigation) cell gets the same work."""
    triples = [
        (task, level, 100 + n)
        for n, (task, level) in enumerate(
            (t, lv) for t in E4_TASKS for lv in ("attainable", "unattainable")
        )
    ]
    arms = [
        {"config_id": cfg, "driver": "minimal-agent", "model": model_of(cfg), "family": FAMILY[cfg]}
        for cfg in CONFIGS
    ]
    runs = [
        {
            "run_id": f"e4-{i:03d}-{cfg}-{mit}",
            "study": "e4",
            "task_id": task,
            "config_id": cfg,
            "conditions": {**BASE, "M1": level},
            "seed": seed,
            "mitigation": mit,
        }
        for cfg in CONFIGS
        for mit in mitigations
        for i, (task, level, seed) in enumerate(triples)
    ]
    notes = json.dumps({"e4_tasks": list(E4_TASKS)})
    return {"study": "e4", "arms": arms, "runs": runs, "notes": notes}


def e1_plan() -> dict[str, Any]:
    """A SYNTHETIC E1 plan that records the E1 and E4 task split in its notes."""
    runs = [
        {"run_id": f"e1-{n:03d}", "task_id": task, "config_id": "ma-qwen7b", "seed": n}
        for n, task in enumerate(E1_TASKS)
    ]
    notes = json.dumps({"e1_tasks": list(E1_TASKS), "e4_tasks": list(E4_TASKS)})
    return {"study": "e1", "runs": runs, "notes": notes}


def e4_pairs(plan: Mapping[str, Any], git_sha: str) -> list[tuple[dict[str, Any], Rescored]]:
    """SYNTHETIC ``(run.json record, rescoring)`` pairs, one per planned E4 run, each run
    from a code snapshot of ``git_sha``."""
    pairs = []
    for n, spec in enumerate(plan["runs"]):
        has_report, false_claim = n % 7 != 0, n % 3 == 0
        report = REPORT if has_report else ""
        claims = [
            {
                "claim_id": "c0",
                "claim_type": "tests_pass",
                "text": "all tests pass",
                "verdict": "contradicted" if false_claim else "supported",
                "evidence": [1],
            }
        ]
        cfg = str(spec["config_id"])
        record = {
            "run_id": spec["run_id"],
            "task_id": spec["task_id"],
            "config_id": cfg,
            "model": model_of(cfg),
            "family": FAMILY[cfg],
            "conditions": dict(spec["conditions"]),
            "seed": spec["seed"],
            "mitigation": spec["mitigation"],
            "report": report,
            "input_tokens": 1000 + n,
            "output_tokens": 100,
            "wall_s": 60.0,
            "model_wall_s": 50.0,
            "hook_checks": [],
            "drafts": [],
            "provenance": snapshot_of(git_sha),
        }
        rescored = Rescored(
            run_id=str(spec["run_id"]),
            report=report,
            stop_reason="finished" if has_report else "max_turns",
            turns=7,
            claims=claims if has_report else [],
            success_reported=has_report,
            ground_truth_success=not false_claim,
            false_success=has_report and false_claim,
            omissions=0,
            runtime_agrees=True,
        )
        pairs.append((record, rescored))
    return pairs


def wilson_entry(successes: int, n: int) -> dict[str, Any]:
    """A Wilson rate as the E4 analysis banks it (bounds are None without runs)."""
    if n == 0:
        return {"successes": 0, "n": 0, "estimate": None, "ci_low": None, "ci_high": None}
    low, high = ship_check.wilson(successes, n)
    return {
        "successes": successes,
        "n": n,
        "estimate": successes / n,
        "ci_low": low,
        "ci_high": high,
    }


def outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The Z1 rates by mitigation, recomputed from ``rows`` (runs with a report)."""
    by_mitigation = {}
    for mit in MITIGATIONS:
        subset = [r for r in rows if r["mitigation"] == mit and r["has_report"]]
        k = sum(1 for r in subset if r["z1_false_claim"])
        by_mitigation[mit] = {"wilson": wilson_entry(k, len(subset))}
    return {"Z1": {"descriptive": {"by_mitigation": by_mitigation}}}


def e4_results(
    rows: list[dict[str, Any]], prereg_sha: str, inputs: Mapping[str, str]
) -> dict[str, Any]:
    """SYNTHETIC artifacts/e4/results.json, confirmatory and citing the frozen prereg."""
    return {
        "confirmatory": True,
        "prereg": PREREG,
        "prereg_sha256": prereg_sha,
        "tasks": sorted({str(r["task_id"]) for r in rows}),
        "rows": rows,
        "outcomes": outcomes(rows),
        "provenance": {**PROV, "inputs": dict(inputs)},
    }


def prereg_text(per_cell: object = PER_CELL, plan_sha: str | None = None, extra: str = "") -> str:
    """A SYNTHETIC E4 preregistration with the machine-readable lines (no
    ``plan_sha256:`` line when ``plan_sha`` is None)."""
    text = f"# E4 (SYNTHETIC test preregistration)\n\nplanned_runs_per_cell: {per_cell}\n"
    if plan_sha is not None:
        text += f"plan_sha256: {plan_sha}\n"
    return text + extra


def lock(prereg_sha: str) -> dict[str, Any]:
    """prereg/LOCK.json freezing the SYNTHETIC E4 preregistration."""
    prev = "0" * 64
    entry = hashlib.sha256(f"{prev}\n{PREREG}\n{prereg_sha}".encode()).hexdigest()
    return {
        "schema": "receipts.prereg-lock/1",
        "entries": [
            {
                "file": PREREG,
                "sha256": prereg_sha,
                "prev": prev,
                "entry_hash": entry,
                "frozen_at": "2026-11-04",
            }
        ],
    }


Records = Callable[[list[dict[str, Any]]], None]
Starts = Callable[[dict[str, Any]], None]
Rows = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
#: Edits a run's ``(kind, data)`` events, given its run id, before its ledger is written.
Ledgers = Callable[[str, list[tuple[str, dict[str, Any]]]], None]


def hidden_checks(truth: bool | None) -> list[tuple[str, dict[str, Any]]]:
    """The post-run ``hidden_check`` event of a SYNTHETIC run whose hidden checks gave
    ``truth`` (no event without a result), with the per-check list and the counts the
    snapshot records."""
    if truth is None:
        return []
    checks = [
        {"name": "SYNTHETIC hidden check one", "passed": True, "requirement": "R1"},
        {"name": "SYNTHETIC hidden check two", "passed": truth, "requirement": "R2"},
    ]
    failed = sum(1 for check in checks if check["passed"] is not True)
    data = {
        "checks": checks,
        "failed": failed,
        "passed": len(checks) - failed,
        "source": "snapshot",
        "total": len(checks),
    }
    return [("hidden_check", data)]


def chained(events: Sequence[tuple[str, Mapping[str, Any]]]) -> list[Event]:
    """SYNTHETIC ``(kind, data)`` events as a hash-chained ledger."""
    out: list[Event] = []
    prev = GENESIS
    for seq, (kind, data) in enumerate(events):
        stamp = 1.0 + seq
        body = dict(data)
        event = Event(
            seq, stamp, kind, body, prev, Event.compute_hash(seq, stamp, kind, body, prev)
        )
        out.append(event)
        prev = event.hash
    return out


def bank(
    root: Path,
    rows: list[dict[str, Any]],
    git_sha: str,
    edit: Records | None = None,
    starts: Starts | None = None,
    ledgers: Ledgers | None = None,
) -> None:
    """Bank a SYNTHETIC run.json and ledger for every E4 row, each recording its arm's
    stand-in model, the minimal-agent driver, and a code snapshot of ``git_sha``, with a
    ``hidden_check`` event of the row's hidden-check result (:func:`hidden_checks`).
    ``edit`` changes the records, ``starts`` each ledger's run_start, and ``ledgers``
    each run's events, before they are written."""
    truths = {str(r["run_id"]): r.get("ground_truth_success") for r in rows}
    records = [
        {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "config_id": r["config_id"],
            "model": model_of(str(r["config_id"])),
            "mitigation": r["mitigation"],
            "seed": r["seed"],
            "conditions": dict(r["conditions"]),
            "report": REPORT if r["has_report"] else "",
            "provenance": snapshot_of(git_sha),
        }
        for r in rows
    ]
    if edit is not None:
        edit(records)
    for record in records:
        run = f"artifacts/studies/e4/runs/{record['run_id']}"
        put(root, f"{run}/run.json", record)
        body = {key: record[key] for key in ("run_id", "task_id", "config_id")}
        body = {**body, "agent": "minimal-agent", "model": record.get("model"), "source": "harness"}
        if starts is not None:
            starts(body)
        events = [("run_start", body), *hidden_checks(truths.get(str(record["run_id"])))]
        if ledgers is not None:
            ledgers(str(record["run_id"]), events)
        lines = "".join(event.to_json() + "\n" for event in chained(events))
        put(root, f"{run}/ledger.jsonl", lines)


#: What the re-derivation step (``tools/bank_study.py e4 --check`` after ``make setup``,
#: DECISIONS D57) prints in a SYNTHETIC project that is given its outcome.
REDERIVED = "e4: SYNTHETIC: the rows are the ones banking writes from the banked runs\n"


def given(name: str, returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    """A sub-command outcome handed to the gate (``ship_check.CmdResult``)."""
    return ship_check.CmdResult(name, returncode, stdout, stderr, 0.0)


def project(
    root: Path,
    commit: Commit,
    *,
    results: Callable[[dict[str, Any]], None] | None = None,
    rows: Rows | None = None,
    banked: Rows | None = None,
    bank_runs: Rows | None = None,
    records: Records | None = None,
    starts: Starts | None = None,
    ledgers: Ledgers | None = None,
    launched: str = "frozen",
    mitigations: tuple[str, ...] = MITIGATIONS,
    plan: dict[str, Any] | None = None,
    split_plan: dict[str, Any] | None = None,
    e1_rows: Sequence[Mapping[str, Any]] | None = None,
    text: Callable[[str], str] | None = None,
    frozen: bool = True,
    instrument: Callable[[dict[str, Any]], None] | None = None,
    changed_instrument: bool = False,
    target: str = "receipts.hook.__main__:main",
    hook_doc: str = HOOK_DOC,
    header: str = "generated by tools/hook_demo.py",
    transcript: str = DEMO_TEXT,
    sleep: float = 0.0,
    extra: Mapping[str, str] | None = None,
) -> ship_check.Context:
    """Write and commit a SYNTHETIC G9 project.

    The instrument is committed first and evaluated there; the tasks, plans, held-out
    evaluation, and prereg follow; then the freeze, which is the commit the runs record
    (``launched``: ``frozen``, or ``drafted`` for the commit before it, or ``changed``
    for a commit after the freeze whose instrument the evaluation never scored, after
    which the evaluated instrument is restored). With ``changed_instrument`` an
    instrument file changes in a later commit and the rows are banked there (else at
    the last commit before the data; ``instrument`` edits that banking record).
    ``plan`` replaces the E4 plan (default: the cells of ``mitigations``),
    ``split_plan`` the E1 plan (an empty dict: none is written), and ``e1_rows`` the E1
    rows. ``text`` makes the E4 prereg from the plan file's SHA-256 (default: both
    lines); it is frozen unless ``frozen`` is false. ``rows`` edits the results' outcome
    rows, ``banked`` the banked rows of artifacts/e4/runs.jsonl, ``results`` the
    results, and ``records``, ``starts``, and ``ledgers`` the banked runs before they are
    written. The runs of the results' rows are banked, or the runs of the outcome rows
    ``bank_runs`` picks from every planned run. The context is given a successful
    re-derivation step (``make setup`` and ``tools/bank_study.py e4 --check``).
    """
    write_instrument(root)
    evaluated = commit(root, "SYNTHETIC instrument")
    for task in E1_TASKS + E4_TASKS:
        put(root, f"bench/tasks/{task}/task.toml", f'id = "{task}"\n')
    the_split = e1_plan() if split_plan is None else split_plan
    if the_split:
        put(root, E1_PLAN, the_split)
    the_plan = e4_plan(mitigations) if plan is None else plan
    put(root, PLAN, the_plan)
    digest_of_plan = sha256(root, PLAN)
    put(
        root, PREREG, prereg_text(plan_sha=digest_of_plan) if text is None else text(digest_of_plan)
    )
    put(root, SEEDED, seeded_eval(root, evaluated))
    drafted = commit(root, "SYNTHETIC tasks, plans, held-out evaluation, and preregistration")
    if frozen:
        put(root, "prereg/LOCK.json", lock(sha256(root, PREREG)))
    freeze = commit(root, "SYNTHETIC freeze")
    commits = {"frozen": freeze, "drafted": drafted}
    banking = freeze
    if launched == "changed":
        write_instrument(root, "v3")
        commits["changed"] = commit(root, "SYNTHETIC run code with an unevaluated instrument")
        write_instrument(root)
        banking = commit(root, "SYNTHETIC instrument restored to the evaluated one")
    if changed_instrument:
        write_instrument(root, "v2")
        banking = commit(root, "SYNTHETIC instrument changed after the evaluation")
    run_commit = commits[launched]
    if e1_rows is None:
        e1_rows = [{"run_id": f"e1-{n:03d}", "task_id": t} for n, t in enumerate(E1_TASKS)]
    put(root, "artifacts/e1/runs.jsonl", "".join(json.dumps(r) + "\n" for r in e1_rows))
    record = instrument_record(root, banking)
    if instrument is not None:
        instrument(record)
    every = e4_rows(e4_pairs(the_plan, run_commit), record, VALID)
    planned = outcome_rows(every, VALID)
    data = outcome_rows(every, VALID)
    if rows is not None:
        data = rows(data)
    kept = {str(r["run_id"]) for r in data}
    banked_rows = [r for r in every if str(r["run_id"]) in kept]
    if banked is not None:
        banked_rows = banked(banked_rows)
    put(root, RUNS, "".join(json.dumps(r, sort_keys=True) + "\n" for r in banked_rows))
    runs = data if bank_runs is None else bank_runs(planned)
    bank(root, runs, run_commit, records, starts, ledgers)
    inputs = {rel: sha256(root, rel) for rel in (RUNS, SEEDED)}
    out = e4_results(data, sha256(root, PREREG), inputs)
    if results is not None:
        results(out)
    put(root, RESULTS, out)
    put(root, "pyproject.toml", PYPROJECT.format(target=target))
    put(root, "src/receipts/__init__.py", "")
    put(root, "src/receipts/hook/__init__.py", "")
    put(root, "src/receipts/hook/__main__.py", HOOK_MODULE)
    put(root, "docs/HOOK.md", hook_doc)
    put(root, "artifacts/hook/latency.json", {"samples_s": [0.2] * 20, "provenance": PROV})
    put(root, "tools/hook_demo.py", DEMO_SCRIPT.format(sleep=sleep, text=DEMO_TEXT))
    put(root, "artifacts/hook/demo_transcript.txt", f"{header}\n{transcript}")
    put(root, "Makefile", MAKEFILE)
    put(root, "README.md", "SYNTHETIC G9 test project\n")
    put(root, ".gitignore", ".venv\n")
    for rel, body in (extra or {}).items():
        put(root, rel, body)
    venv = root / ".venv"
    if not venv.exists():
        venv.symlink_to(sys.prefix, target_is_directory=True)
    sha = commit(root, "SYNTHETIC G9 project")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    ctx = ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)
    ctx.results["make-setup"] = given("make-setup")
    ctx.results["bank-check-e4"] = given("bank-check-e4", stdout=REDERIVED)
    ctx.results[f"derived-{RESULTS}"] = derived_ok(RESULTS, "python tools/analyze_e4.py")
    return ctx


def needs_runner() -> None:
    """Skip when the demo script cannot be re-run offline here."""
    if not (shutil.which("uv") and shutil.which("make")) or sys.prefix == sys.base_prefix:
        pytest.skip("needs make, uv, and a virtualenv to link synthetic projects to")
    if ship_check.network_isolation() is None:
        pytest.skip("no working network isolation (unshare -rn, bwrap, sandbox-exec)")


def e4_results_of(ctx: ship_check.Context) -> dict[str, Any]:
    """The committed SYNTHETIC artifacts/e4/results.json."""
    data = json.loads((ctx.clone / RESULTS).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def check_e4(ctx: ship_check.Context) -> tuple[int, int]:
    """``ship_check.check_e4`` on the committed SYNTHETIC results."""
    return ship_check.check_e4(ctx.clone, e4_results_of(ctx))


def test_a_complete_mitigation_package_passes(git_repo: Path, commit: Commit) -> None:
    needs_runner()
    evidence = ship_check.g9(project(git_repo, commit))
    assert "E4 on 2 held-out tasks" in evidence and "demo transcript reproduces" in evidence
    assert "evaluated instrument" in evidence
    assert "re-derived from the 32 banked runs" in evidence
    assert f"{RESULTS} re-derived by tools/analyze_e4.py" in evidence


def test_the_e4_fixture_passes_the_e4_checks(git_repo: Path, commit: Commit) -> None:
    assert check_e4(project(git_repo, commit)) == (2, 32)


# ---------------------------------------------------------------- confirmatory, frozen prereg


def test_exploratory_e4_results_fail(git_repo: Path, commit: Commit) -> None:
    def exploratory(results: dict[str, Any]) -> None:
        results["confirmatory"] = False

    with pytest.raises(GateError, match="not marked confirmatory"):
        check_e4(project(git_repo, commit, results=exploratory))


def test_results_citing_an_unfrozen_preregistration_fail(git_repo: Path, commit: Commit) -> None:
    with pytest.raises(GateError, match="is not frozen"):
        check_e4(project(git_repo, commit, frozen=False))


def test_results_citing_the_prereg_with_another_digest_fail(git_repo: Path, commit: Commit) -> None:
    def other(results: dict[str, Any]) -> None:
        results["prereg_sha256"] = "0" * 64

    with pytest.raises(GateError, match="other than its frozen one"):
        check_e4(project(git_repo, commit, results=other))


# ---------------------------------------------------------------- plan lines and cells [12]


@pytest.mark.parametrize(
    ("make_text", "match"),
    [
        pytest.param(
            lambda digest: prereg_text(per_cell="TO FIX BEFORE FREEZE", plan_sha=digest),
            "does not state planned_runs_per_cell",
            id="no-runs-per-cell",
        ),
        pytest.param(lambda digest: prereg_text(), "has no plan_sha256: line", id="no-digest"),
        pytest.param(
            lambda digest: prereg_text(plan_sha="ab" * 32, extra=f"plan_sha256: {digest}\n"),
            "records a plan_sha256 that is not the SHA-256",
            id="first-digest-wrong",
        ),
        pytest.param(
            lambda digest: prereg_text(per_cell=8, plan_sha=digest),
            "differ from planned_runs_per_cell = 8",
            id="other-runs-per-cell",
        ),
    ],
)
def test_the_prereg_lines_fix_the_plan(
    git_repo: Path, commit: Commit, make_text: Callable[[str], str], match: str
) -> None:
    with pytest.raises(GateError, match=match):
        check_e4(project(git_repo, commit, text=make_text))


def test_a_cell_with_more_runs_than_the_others_fails(git_repo: Path, commit: Commit) -> None:
    plan = e4_plan()
    extra = dict(plan["runs"][0], run_id="e4-099-ma-qwen7b-none", seed=999)
    plan["runs"].append(extra)
    with pytest.raises(GateError, match=r"ma-qwen7b/none=5"):
        check_e4(project(git_repo, commit, plan=plan))


@pytest.mark.parametrize(
    "change",
    [pytest.param({"seed": 4242}, id="seed"), pytest.param({"task_id": "py-e4-gamma"}, id="task")],
)
def test_cells_on_different_work_fail(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    # Every cell keeps N runs, but one hook-arm triple is not the others' triple.
    plan = e4_plan()
    target = next(
        i
        for i, s in enumerate(plan["runs"])
        if s["mitigation"] == "hook" and s["task_id"] == "py-e4-delta"
    )
    plan["runs"][target] = dict(plan["runs"][target], **change)
    with pytest.raises(GateError, match="do not share one identical list"):
        check_e4(project(git_repo, commit, plan=plan))


# ---------------------------------------------------------------- H18 (old code: PASS)


def set_tasks(tasks: object) -> Callable[[dict[str, Any]], None]:
    """Replace the reported E4 task list."""

    def apply(results: dict[str, Any]) -> None:
        results["tasks"] = tasks

    return apply


@pytest.mark.parametrize(
    "tasks",
    [
        pytest.param("py-e4-gamma", id="a-string"),
        pytest.param(["no-such-task"], id="unknown-task"),
        pytest.param(["bench/tasks/py-e4-gamma", "py-e4-delta"], id="path-form"),
        pytest.param(["py-e4-gamma"], id="fewer-than-the-runs"),
    ],
)
def test_the_task_list_must_be_the_runs_tasks(
    git_repo: Path, commit: Commit, tasks: object
) -> None:
    ctx = project(git_repo, commit, results=set_tasks(tasks))
    with pytest.raises(GateError, match="E4 tasks"):
        ship_check.g9(ctx)


def retask(task: str) -> Rows:
    """Move every run of py-e4-delta onto ``task`` (rows and plan disagree then)."""

    def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(r, task_id=task) if r["task_id"] == "py-e4-delta" else r for r in rows]

    return apply


def plan_on(task: str, *, notes: Sequence[str] = E4_TASKS) -> dict[str, Any]:
    """The SYNTHETIC E4 plan with every run of py-e4-delta moved onto ``task``."""
    plan = e4_plan()
    for spec in plan["runs"]:
        if spec["task_id"] == "py-e4-delta":
            spec["task_id"] = task
    plan["notes"] = json.dumps({"e4_tasks": list(notes)})
    return plan


def test_runs_on_an_e1_task_behind_a_held_out_task_list_fail(
    git_repo: Path, commit: Commit
) -> None:
    # The runs used an E1 task; the reported task list still names held-out tasks.
    ctx = project(git_repo, commit, rows=retask("py-e1-alpha"), results=set_tasks(list(E4_TASKS)))
    with pytest.raises(GateError, match="differs from its planned run"):
        ship_check.g9(ctx)


def test_a_plan_that_puts_e4_runs_on_an_e1_task_fails(git_repo: Path, commit: Commit) -> None:
    ctx = project(git_repo, commit, plan=plan_on("py-e1-alpha"))
    with pytest.raises(GateError, match="overlap E1"):
        ship_check.g9(ctx)


def test_a_planned_e4_task_that_is_an_e1_task_fails_even_unrun(
    git_repo: Path, commit: Commit
) -> None:
    # Only the runs on held-out tasks were banked; the plan still puts runs on an E1 task.
    def unrun(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in rows if r["task_id"] != "py-e1-alpha"]

    ctx = project(git_repo, commit, plan=plan_on("py-e1-alpha"), rows=unrun)
    with pytest.raises(GateError, match="overlap E1"):
        check_e4(ctx)


def test_a_pilot_task_is_not_held_out(git_repo: Path, commit: Commit) -> None:
    plan = plan_on("pilot-csv-stats", notes=("py-e4-gamma", "pilot-csv-stats"))
    pilot = {"bench/tasks/pilot-csv-stats/task.toml": 'id = "pilot-csv-stats"\n'}
    ctx = project(git_repo, commit, plan=plan, extra=pilot)
    with pytest.raises(GateError, match="not held-out benchmark tasks"):
        ship_check.g9(ctx)


def test_runs_outside_the_e4_plan_fail(git_repo: Path, commit: Commit) -> None:
    def foreign(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [*rows, dict(rows[0], run_id="e4-foreign-run")]

    with pytest.raises(GateError, match="not a planned E4 run"):
        ship_check.g9(project(git_repo, commit, rows=foreign))


def test_an_e4_row_without_its_banked_run_fails(git_repo: Path, commit: Commit) -> None:
    def drop(records: list[dict[str, Any]]) -> None:
        del records[3]

    with pytest.raises(GateError, match=r"run\.json missing"):
        ship_check.g9(project(git_repo, commit, records=drop))


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"mitigation": "honesty"}, id="mitigation"),
        pytest.param({"report": ""}, id="has-report"),
        pytest.param({"report": "SYNTHETIC report: other words."}, id="report"),
        pytest.param({"seed": 7}, id="seed"),
    ],
)
def test_e4_rows_must_agree_with_their_banked_runs(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edit(records: list[dict[str, Any]]) -> None:
        # A control run with a report, so every change differs from what it records.
        target = next(r for r in records if r["mitigation"] == "none" and r["report"])
        target.update(change)

    with pytest.raises(GateError, match=r"differs from its banked run\.json"):
        ship_check.g9(project(git_repo, commit, records=edit))


def test_a_mitigation_that_never_ran_fails(git_repo: Path, commit: Commit) -> None:
    def no_hook(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in rows if r["mitigation"] != "hook"]

    with pytest.raises(GateError, match="no runs for mitigation"):
        ship_check.g9(project(git_repo, commit, rows=no_hook))


def test_synthetic_e4_runs_fail(git_repo: Path, commit: Commit) -> None:
    def marked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(r, synthetic=True) for r in rows]

    with pytest.raises(GateError, match="synthetic"):
        ship_check.g9(project(git_repo, commit, rows=marked))


def test_a_z1_rate_that_does_not_recompute_fails(git_repo: Path, commit: Commit) -> None:
    def typed(results: dict[str, Any]) -> None:
        entry = results["outcomes"]["Z1"]["descriptive"]["by_mitigation"]["hook"]["wilson"]
        entry.update(successes=0, estimate=0.0)

    with pytest.raises(GateError, match="Z1"):
        ship_check.g9(project(git_repo, commit, results=typed))


# ---------------------------------------------------------------- both held-out lists [18]


@pytest.mark.parametrize(
    ("split_plan", "match"),
    [
        pytest.param({}, "held-out E4 split it records is unknown", id="no-e1-plan"),
        pytest.param(
            {"study": "e1", "runs": [], "notes": json.dumps({"e1_tasks": list(E1_TASKS)})},
            "records no held-out E4 split",
            id="no-split",
        ),
        pytest.param(
            {"study": "e1", "runs": [], "notes": json.dumps({"e4_tasks": []})},
            "records no held-out E4 split",
            id="an-empty-split",
        ),
        pytest.param(
            {"study": "e1", "runs": [], "notes": "SYNTHETIC notes, not JSON"},
            "records no held-out E4 split",
            id="notes-not-json",
        ),
    ],
)
def test_the_held_out_split_must_be_known(
    git_repo: Path, commit: Commit, split_plan: dict[str, Any], match: str
) -> None:
    with pytest.raises(GateError, match=match):
        check_e4(project(git_repo, commit, split_plan=split_plan))


def test_e1_task_ids_must_be_known(git_repo: Path, commit: Commit) -> None:
    # No E1 row, planned E1 run, or e1_tasks list: disjointness would compare nothing.
    split = {"study": "e1", "runs": [], "notes": json.dumps({"e4_tasks": list(E4_TASKS)})}
    ctx = project(git_repo, commit, split_plan=split, e1_rows=[])
    with pytest.raises(GateError, match="E1's task ids are unknown or empty"):
        check_e4(ctx)


def test_e4_tasks_must_be_in_the_recorded_split(git_repo: Path, commit: Commit) -> None:
    split = dict(e1_plan(), notes=json.dumps({"e4_tasks": ["py-e4-gamma"]}))
    with pytest.raises(GateError, match="not in the held-out split the E1 plan records"):
        check_e4(project(git_repo, commit, split_plan=split))


# ---------------------------------------------------------------- the evaluated instrument (D42)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"instrument_dirty": True}, id="instrument-dirty"),
        pytest.param({"instrument": {"commit": "0" * 40, "trees": {}}}, id="other-trees"),
    ],
)
def test_results_rows_must_come_from_the_evaluated_instrument(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edited(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[5].update(change)
        return rows

    with pytest.raises(GateError, match="does not come from the evaluated instrument"):
        check_e4(project(git_repo, commit, rows=edited))


def test_banked_rows_from_uncommitted_code_fail(git_repo: Path, commit: Commit) -> None:
    def dirty(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[0]["instrument"] = dict(rows[0]["instrument"], dirty=True)
        return rows

    with pytest.raises(GateError, match="banked from code with uncommitted changes"):
        check_e4(project(git_repo, commit, banked=dirty))


def test_rows_that_claim_the_evaluated_trees_at_another_commit_fail(
    git_repo: Path, commit: Commit
) -> None:
    def forged(record: dict[str, Any]) -> None:
        evaluated = json.loads((git_repo / SEEDED).read_text("utf-8"))["instrument"]["trees"]
        record["trees"] = evaluated

    ctx = project(git_repo, commit, changed_instrument=True, instrument=forged)
    with pytest.raises(GateError, match="does not hold the instrument of the evaluated commit"):
        check_e4(ctx)


def test_the_banked_rows_must_be_the_results_runs(git_repo: Path, commit: Commit) -> None:
    def short(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows[1:]

    with pytest.raises(GateError, match=r"are not the runs of artifacts/e4/runs\.jsonl"):
        check_e4(project(git_repo, commit, banked=short))


@pytest.mark.parametrize("rel", [pytest.param(RUNS, id="rows"), pytest.param(SEEDED, id="eval")])
def test_results_computed_from_other_inputs_fail(git_repo: Path, commit: Commit, rel: str) -> None:
    def other(results: dict[str, Any]) -> None:
        results["provenance"]["inputs"][rel] = "0" * 64

    with pytest.raises(GateError, match=f"was not computed from the committed {rel}"):
        check_e4(project(git_repo, commit, results=other))


def test_an_e4_study_needs_the_held_out_evaluation(git_repo: Path, commit: Commit) -> None:
    project(git_repo, commit)
    (git_repo / SEEDED).unlink()
    commit(git_repo, "drop the held-out evaluation")
    ctx = ship_check.Context(
        orig=git_repo, clone=git_repo, logs=git_repo.parent / "logs", fast=False, sha="0" * 40
    )
    with pytest.raises(GateError, match=r"seeded_eval\.json missing"):
        check_e4(ctx)


@pytest.mark.parametrize("mode", [None, "no_requirements"])
def test_an_evaluation_in_another_verifier_mode_fails(
    git_repo: Path, commit: Commit, mode: str | None
) -> None:
    # Scored without each report's task requirements, the held-out evaluation did not
    # evaluate the instrument the hook arm runs (prereg 0002 section 7, DECISIONS D54).
    project(git_repo, commit)
    evaluation = json.loads((git_repo / SEEDED).read_text("utf-8"))
    if mode is None:
        del evaluation["verifier_mode"]
    else:
        evaluation["verifier_mode"] = mode
    put(git_repo, SEEDED, evaluation)
    sha = commit(git_repo, "an evaluation in another verifier mode")
    ctx = ship_check.Context(
        orig=git_repo, clone=git_repo, logs=git_repo.parent / "logs", fast=False, sha=sha
    )
    with pytest.raises(GateError, match="verifier mode"):
        check_e4(ctx)


# ---------------------------------------------------------------- review-1 (old code: PASS)


@pytest.mark.parametrize(
    ("driver", "model"),
    [
        pytest.param("minimal-agent", "mock-model", id="mock-model"),
        pytest.param("scripted-driver", model_of("ma-qwen7b"), id="scripted-driver"),
    ],
)
def test_e4_runs_by_a_mock_or_scripted_agent_fail(
    git_repo: Path, commit: Commit, driver: str, model: str
) -> None:
    # Every row says synthetic: false; the banked runs say who really ran.
    def records(recs: list[dict[str, Any]]) -> None:
        for record in recs:
            record["model"] = model

    def starts(body: dict[str, Any]) -> None:
        body.update(agent=driver, model=model)

    with pytest.raises(GateError, match="which is not an agent"):
        ship_check.g9(project(git_repo, commit, records=records, starts=starts))


def test_an_e4_run_by_another_agent_than_its_arm_fails(git_repo: Path, commit: Commit) -> None:
    # A real agent, but the other arm's model under this run's configuration.
    def records(recs: list[dict[str, Any]]) -> None:
        target = next(r for r in recs if r["run_id"] == "e4-002-ma-qwen7b-none")
        target["model"] = model_of("ma-granite8b")

    def starts(body: dict[str, Any]) -> None:
        if body["run_id"] == "e4-002-ma-qwen7b-none":
            body["model"] = model_of("ma-granite8b")

    with pytest.raises(GateError, match="not by its planned agent"):
        ship_check.g9(project(git_repo, commit, records=records, starts=starts))


def test_an_e4_plan_arm_without_its_agent_fails(git_repo: Path, commit: Commit) -> None:
    plan = e4_plan()
    del plan["arms"][1]["model"]
    with pytest.raises(GateError, match="arm without a config_id, driver, or model"):
        ship_check.g9(project(git_repo, commit, plan=plan))


# ---------------------------------------------------------------- review-2 (old code: PASS)


@pytest.mark.parametrize(
    "mitigations",
    [
        pytest.param(("none",), id="no-mitigation"),
        pytest.param(("hook",), id="no-control"),
        pytest.param(("honesty", "hook"), id="mitigations-without-control"),
    ],
)
def test_an_e4_study_without_a_comparison_fails(
    git_repo: Path, commit: Commit, mitigations: tuple[str, ...]
) -> None:
    # Every planned arm ran and every rate recomputes, but nothing is compared with a
    # no-mitigation control, so no mitigation's effect was measured.
    with pytest.raises(GateError, match="compares no mitigation with the no-mitigation arm"):
        ship_check.g9(project(git_repo, commit, mitigations=mitigations))


def test_a_plan_without_every_mitigation_fails(git_repo: Path, commit: Commit) -> None:
    # A control and one mitigation are a comparison, but prereg 0002 section 3 plans all
    # four mitigations in both configurations, and the E4 analysis refuses absent cells.
    with pytest.raises(GateError, match="no runs in cell"):
        check_e4(project(git_repo, commit, mitigations=("none", "hook")))


def test_gate_constants_follow_the_code_they_mirror() -> None:
    # ship_check imports nothing from receipts, so its copies are checked here.
    assert ship_check.ROW_INSTRUMENT_PATHS == INSTRUMENT_RECORD_PATHS
    assert ship_check.E4_CONFIGURATIONS == results_e4.CONFIGURATIONS
    assert ship_check.E4_MITIGATIONS == study_spec.MITIGATIONS
    assert ship_check.E3_MAX_ATTEMPTS == e3.MAX_ATTEMPTS


def test_the_full_design_passes(git_repo: Path, commit: Commit) -> None:
    assert ship_check.E4_CONFIGURATIONS == CONFIGS
    assert ship_check.E4_MITIGATIONS == MITIGATIONS
    assert check_e4(project(git_repo, commit)) == (2, 32)


def cell_runs(configs: Sequence[str], skip: tuple[str, str] | None = None) -> dict[str, Any]:
    """SYNTHETIC planned E4 runs: two per (configuration, mitigation) cell of ``configs``,
    on one identical list of triples, without the cell ``skip``."""
    return {
        f"r{i}-{c}-{m}": {
            "run_id": f"r{i}-{c}-{m}",
            "config_id": c,
            "mitigation": m,
            "task_id": "py-a",
            "conditions": {"M1": "attainable"},
            "seed": i,
        }
        for i in range(2)
        for c in configs
        for m in MITIGATIONS
        if (c, m) != skip
    }


def test_the_cell_check_takes_exactly_the_preregistered_cells() -> None:
    text = "planned_runs_per_cell: 2"
    assert ship_check.check_e4_cells("prereg", text, cell_runs(CONFIGS), CONFIGS) == 2
    with pytest.raises(GateError, match=r"no runs in cell.*ma-granite8b/evidence"):
        ship_check.check_e4_cells(
            "prereg", text, cell_runs(CONFIGS, ("ma-granite8b", "evidence")), CONFIGS
        )
    # An arm of the plan with no runs at all leaves four cells empty.
    with pytest.raises(GateError, match="no runs in cell"):
        ship_check.check_e4_cells("prereg", text, cell_runs(("ma-qwen7b",)), CONFIGS)
    with pytest.raises(GateError, match="not the configurations"):
        ship_check.check_e4_cells("prereg", text, cell_runs(CONFIGS), ("ma-qwen7b",))
    other = {**cell_runs(CONFIGS), "x": {**cell_runs(CONFIGS)["r0-ma-qwen7b-none"]}}
    other["x"]["mitigation"] = "shame"
    with pytest.raises(GateError, match=r"outside it.*ma-qwen7b/shame"):
        ship_check.check_e4_cells("prereg", text, other, CONFIGS)


# ---------------------------------------------------------------- H29 (old code: PASS)


@pytest.mark.parametrize(
    "target",
    ["receipts.hook.gone:main", "receipts.hook.__main__:absent", "receipts.hook.__main__"],
    ids=["missing-module", "missing-function", "no-function"],
)
def test_an_entry_point_that_does_not_resolve_fails(
    git_repo: Path, commit: Commit, target: str
) -> None:
    with pytest.raises(GateError, match="receipts-hook entry point"):
        ship_check.g9(project(git_repo, commit, target=target))


@pytest.mark.parametrize(
    "hook_doc",
    [
        pytest.param(
            "# hook\n\n## Uninstall\n\nRemove it.\n\n```bash\n# install it with uv sync\n```\n",
            id="uninstall-and-a-code-comment",
        ),
        pytest.param("# hook\n\n## Installation\n\n## Usage\n\nRun it.\n", id="empty-section"),
    ],
)
def test_install_instructions_must_be_a_real_section(
    git_repo: Path, commit: Commit, hook_doc: str
) -> None:
    with pytest.raises(GateError, match="install instructions"):
        ship_check.g9(project(git_repo, commit, hook_doc=hook_doc))


def test_the_entry_point_resolver() -> None:
    names = ship_check.top_level_names(
        "import os as main_os\nfrom x import y as run\ndef a(): ...\nclass B: ...\n"
        "c: int = 1\nd = e = 2\nif True:\n    f = 3\n"
        "try:\n    g = 4\nexcept Exception:\n    h = 5\n"
    )
    assert {"main_os", "run", "a", "B", "c", "d", "e", "f", "g", "h"} <= names


# ---------------------------------------------------------------- H28 (old code: PASS)


@pytest.mark.parametrize(
    "header",
    [
        "generated by /bin/sh",
        "generated by README.md -- typed by hand",
        "generated by ../outside.py",
        "generated by tools/not_there.py",
    ],
    ids=["outside-the-clone", "any-file", "parent-path", "untracked"],
)
def test_the_transcript_must_name_a_tracked_demo_script(
    git_repo: Path, commit: Commit, header: str
) -> None:
    with pytest.raises(GateError, match="generating script"):
        ship_check.g9(project(git_repo, commit, header=header))


def test_a_hand_typed_transcript_fails(git_repo: Path, commit: Commit) -> None:
    needs_runner()
    ctx = project(git_repo, commit, transcript="SYNTHETIC: typed by hand, never run\n")
    with pytest.raises(GateError, match="differs from the committed demo transcript"):
        ship_check.g9(ctx)


def test_a_demo_longer_than_30_seconds_fails(
    git_repo: Path, commit: Commit, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The limit is lowered so the slow demo stays fast in the test.
    needs_runner()
    monkeypatch.setattr(ship_check, "HOOK_DEMO_LIMIT_S", 0.5)
    with pytest.raises(GateError, match="took"):
        ship_check.g9(project(git_repo, commit, sleep=1.5))


# ---------------------------------------------------------------- review B2 and N6 (old code: PASS)

# Planned run e4-001-ma-qwen7b-none has a report, a success claim, and passed hidden
# checks; e4-003-ma-qwen7b-none has a report, a success claim, and a failed hidden check
# (a false success and a false claim); see e4_pairs.
PASSED_RUN = "e4-001-ma-qwen7b-none"
FAILED_RUN = "e4-003-ma-qwen7b-none"


def test_an_e4_run_banked_without_a_row_fails(git_repo: Path, commit: Commit) -> None:
    # Every planned run is banked, but the rows of artifacts/e4/runs.jsonl and of the
    # results leave one out, and the Z1 rates recompute from the rows that remain.
    ctx = project(git_repo, commit, rows=lambda rows: rows[1:], bank_runs=lambda every: every)
    with pytest.raises(
        GateError,
        match=r"1 run\(s\) banked under artifacts/studies/e4/runs/ have no row in "
        r"artifacts/e4/runs\.jsonl",
    ):
        ship_check.g9(ctx)


def banked_truth(run_id: str, truth: bool | None) -> Ledgers:
    """Bank the hidden checks of run ``run_id`` as giving ``truth``."""

    def apply(rid: str, events: list[tuple[str, dict[str, Any]]]) -> None:
        if rid == run_id:
            events[:] = [e for e in events if e[0] != "hidden_check"] + hidden_checks(truth)

    return apply


def edit_run_row(run_id: str, **change: Any) -> Rows:
    """Change fields of the row of run ``run_id``."""

    def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if row["run_id"] == run_id:
                row.update(change)
        return rows

    return apply


@pytest.mark.parametrize(
    ("ledgers", "banked", "field"),
    [
        pytest.param(
            banked_truth(PASSED_RUN, False),
            None,
            "ground_truth_success",
            id="passed-row-failed-ledger",
        ),
        pytest.param(
            banked_truth(FAILED_RUN, True),
            None,
            "ground_truth_success",
            id="failed-row-passed-ledger",
        ),
        pytest.param(
            banked_truth(PASSED_RUN, None),
            None,
            "ground_truth_success",
            id="no-result-in-the-ledger",
        ),
        pytest.param(
            None,
            edit_run_row(FAILED_RUN, false_success=False),
            "false_success",
            id="false-success-left-out",
        ),
    ],
)
def test_e4_rows_must_be_what_the_banked_ledger_shows(
    git_repo: Path, commit: Commit, ledgers: Ledgers | None, banked: Rows | None, field: str
) -> None:
    ctx = project(git_repo, commit, ledgers=ledgers, banked=banked)
    with pytest.raises(GateError, match=rf"differs from its banked ledger in .*{field}"):
        ship_check.g9(ctx)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"z1_false_claim": True}, id="z1"),
        pytest.param({"success_reported": False}, id="success-claim"),
        pytest.param({"z2_false_success": True}, id="z2"),
    ],
)
def test_results_rows_must_be_the_outcome_rows_of_the_banked_rows(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    # The Z1 rates recompute from the results' own rows, so an edited flag shows only
    # against the banked row, which banking re-derives.
    ctx = project(git_repo, commit, rows=edit_run_row(PASSED_RUN, **change))
    (field,) = change
    with pytest.raises(GateError, match=rf"is not the outcome row of its banked row in .*{field}"):
        ship_check.g9(ctx)


@pytest.mark.parametrize(
    ("launched", "match"),
    [
        pytest.param(
            "changed",
            "ran code whose instrument is not the evaluated one",
            id="an-unevaluated-instrument",
        ),
        pytest.param(
            "drafted",
            r"was launched from [0-9a-f]{12}, not from the freeze commit",
            id="before-the-freeze",
        ),
    ],
)
def test_an_e4_run_must_run_the_evaluated_instrument_from_the_freeze_on(
    git_repo: Path, commit: Commit, launched: str, match: str
) -> None:
    # The rows are banked from the evaluated instrument either way; only the commit the
    # runs record differs (DECISIONS D47: G9 compares an E4 run commit's trees).
    with pytest.raises(GateError, match=match):
        ship_check.g9(project(git_repo, commit, launched=launched))


def recorded_code(**change: Any) -> Records:
    """Change the code record of the first banked run (a value of None removes a key)."""

    def apply(recs: list[dict[str, Any]]) -> None:
        prov = recs[0]["provenance"]
        for key, value in change.items():
            if value is None:
                prov.pop(key, None)
            else:
                prov[key] = value

    return apply


DID_NOT_RUN_IT = "did not run the code of the commit it records"


@pytest.mark.parametrize(
    ("records", "match"),
    [
        pytest.param(
            recorded_code(snapshot_of="0" * 40), DID_NOT_RUN_IT, id="a-snapshot-of-another-commit"
        ),
        pytest.param(
            recorded_code(
                code="working tree",
                snapshot_of=None,
                uncommitted_at_start=["src/receipts/verify/verifier.py"],
            ),
            DID_NOT_RUN_IT,
            id="uncommitted-src",
        ),
        pytest.param(
            recorded_code(
                code="working tree",
                snapshot_of=None,
                uncommitted_at_start=["docs/SYNTHETIC.py -> src/receipts/SYNTHETIC.py"],
            ),
            DID_NOT_RUN_IT,
            id="a-rename-into-src",
        ),
        pytest.param(
            recorded_code(code="working tree", snapshot_of=None),
            DID_NOT_RUN_IT,
            id="an-unrecorded-working-tree",
        ),
        pytest.param(recorded_code(code=None, snapshot_of=None), DID_NOT_RUN_IT, id="no-code"),
        pytest.param(
            recorded_code(git_sha="1" * 40, snapshot_of="1" * 40),
            "was launched from 111111111111",
            id="a-commit-outside-the-repository",
        ),
        pytest.param(recorded_code(git_sha=None), "was launched from None", id="no-commit"),
    ],
)
def test_an_e4_run_must_record_the_committed_code_it_ran(
    git_repo: Path, commit: Commit, records: Records, match: str
) -> None:
    with pytest.raises(GateError, match=match):
        check_e4(project(git_repo, commit, records=records))


def test_an_e4_run_from_a_clean_working_tree_passes(git_repo: Path, commit: Commit) -> None:
    # Uncommitted files outside src/ leave the run's code the commit it records.
    clean = recorded_code(
        code="working tree", snapshot_of=None, uncommitted_at_start=["README.md", '"docs/a b.md"']
    )
    assert check_e4(project(git_repo, commit, records=clean)) == (2, 32)


def test_e4_rows_that_banking_does_not_write_fail(git_repo: Path, commit: Commit) -> None:
    # Claims and verdicts need the extractor and the verifier, so g9 has
    # tools/bank_study.py re-derive every row in the clone (DECISIONS D57).
    ctx = project(git_repo, commit)
    ctx.results["bank-check-e4"] = given(
        "bank-check-e4",
        1,
        stderr="bank_study e4 --check: 1 row(s) differ from the rows banking writes now in "
        "claims: SYNTHETIC-run\n",
    )
    with pytest.raises(
        GateError, match=r"artifacts/e4/runs\.jsonl is not what banking writes from the banked"
    ):
        ship_check.g9(ctx)


@pytest.mark.parametrize(
    "where",
    [
        pytest.param("outcomes.Z1.holm.reject.0", id="a-hand-set-test-decision"),
        pytest.param("outcomes.Z1.contrasts.0.odds_ratio", id="a-hand-set-odds-ratio"),
        pytest.param("outcomes.Z1.contrasts.0.p_value", id="a-hand-set-p-value"),
    ],
)
def test_e4_results_that_are_not_a_fresh_derivation_fail(
    git_repo: Path, commit: Commit, where: str
) -> None:
    # The Z1 rates recompute from the rows, but a test result needs the mixed models, so
    # g9 has python -m receipts.report.derived derive the results again in the clone
    # (DECISIONS D65); the step fails before the hook is checked.
    ctx = project(git_repo, commit)
    ctx.results[f"derived-{RESULTS}"] = derived_fails(RESULTS, where, "tools/analyze_e4.py")
    with pytest.raises(GateError, match=rf"{RESULTS} is not a fresh derivation .*\({where}\)"):
        ship_check.g9(ctx)


def test_the_gate_re_derives_the_e4_results_and_a_hand_set_test_result_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's step itself, on the SYNTHETIC study whose results tools/analyze_e4.py
    wrote (tests/report/studies.py): they pass, and a typed Holm decision and odds ratio
    fail with the paths that differ."""
    from tests.report import studies

    root = studies.e4_study(tmp_path / "e4")

    def gate_context() -> ship_check.Context:
        ctx = ship_check.Context(orig=root, clone=root, logs=tmp_path, fast=False, sha="0")
        ctx.results["make-setup"] = given("make-setup")
        run_for_real(ctx, monkeypatch)
        return ctx

    first = gate_context()
    ship_check.check_derivation(first, RESULTS)
    assert "re-derived by python tools/analyze_e4.py" in first.results[f"derived-{RESULTS}"].stdout

    def hand_set(data: dict[str, Any]) -> None:
        z1 = data["outcomes"]["Z1"]
        z1["holm"]["reject"][0] = not z1["holm"]["reject"][0]
        z1["contrasts"][0]["odds_ratio"] *= 2

    studies.edit(root, RESULTS, hand_set)
    match = r"outcomes\.Z1\.contrasts\.0\.odds_ratio, outcomes\.Z1\.holm\.reject\.0"
    with pytest.raises(GateError, match=match):
        ship_check.check_derivation(gate_context(), RESULTS)


#: A SYNTHETIC stand-in for tools/bank_study.py that checks the arguments it is given.
STAND_IN = '''"""SYNTHETIC stand-in for tools/bank_study.py in the gate tests: it checks the
arguments the gate passes and prints one line; it re-derives nothing."""

import sys

if sys.argv[1:] != [{study!r}, "--check"]:
    sys.exit(f"SYNTHETIC stand-in: unexpected arguments {{sys.argv[1:]}}")
print("{study}: SYNTHETIC stand-in re-derivation passed")
'''


def test_the_gate_runs_the_rederivation_in_the_clone(git_repo: Path, commit: Commit) -> None:
    needs_runner()
    ctx = project(git_repo, commit, extra={"tools/bank_study.py": STAND_IN.format(study="e4")})
    del ctx.results["make-setup"], ctx.results["bank-check-e4"]
    assert "re-derived from the 32 banked runs" in ship_check.g9(ctx)
    step = ctx.results["bank-check-e4"]
    assert step.ok and "SYNTHETIC stand-in re-derivation passed" in step.stdout
