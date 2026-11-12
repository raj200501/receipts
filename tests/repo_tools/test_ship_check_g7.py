"""Gate G7 of tools/ship_check.py on a synthetic E1 history (H13, H15, H16, H24 to H26,
review-1 of the harness review round, the pre-freeze items: Y1 over the runs with a
hidden-check result, the required plan digest, and the evaluated instrument of
DECISIONS D42, and review B2 of the e4230cc review: rows that cover every banked run and
outcomes re-derived from the banked runs, DECISIONS D57).

Every preregistration, plan, instrument file, held-out evaluation, run row, ledger, and
result here is SYNTHETIC, made up only to exercise ``ship_check.g7`` in throwaway git
repositories. Rows are marked ``synthetic: false`` only so the gate treats them as real
runs, the arms' models are stand-in names, the instrument files are stand-ins whose only
role is to have git trees, the hidden-check results are made up, and the "results" are
recomputed from those rows; nothing here is a model result or a real-world result. The
SYNTHETIC clones hold no project for ``tools/bank_study.py --check`` or for the
re-derivation of the results (``python -m receipts.report.derived``, DECISIONS D65) to run
in, so g7 is given those steps' outcomes (:func:`context`), except in the tests that run a
stand-in or the real re-derivation (on the SYNTHETIC study of tests/report/studies.py,
whose results are what tools/analyze.py writes).
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

import receipts
import ship_check
from receipts.analysis.rates import rate_with_ci
from receipts.ledger.events import GENESIS, Event, Ledger, sha256_text
from receipts.study.aggregate import e1_rows
from receipts.study.plan import Plan, factorial_plan, local_arm
from receipts.study.rescore import INSTRUMENT_RECORD_PATHS, Rescored
from receipts.study.spec import StudyText
from receipts.verify.facts import LedgerFacts

Commit = Callable[[Path, str], str]
GateError = ship_check.GateError
#: Where the receipts package that this test process runs comes from.
SRC = Path(str(receipts.__file__)).resolve().parents[1]

ARM_FAMILY = {
    "ma-qwen7b": "qwen",
    "ma-qwen1.5b": "qwen",
    "ma-granite8b": "granite",
    "ma-granite2b": "granite",
}
REPLICATES = 4  # 16 cells x 4 = 64 planned runs per arm
PREREG = "prereg/0001-e1-synthetic.md"
PLAN = "artifacts/studies/e1/plan.json"
RUNS = "artifacts/e1/runs.jsonl"
RESULTS = "artifacts/e1/results.json"
SEEDED = "artifacts/e0/seeded_eval.json"
REPORT = "SYNTHETIC report: all tests pass."
PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}


def put(root: Path, rel: str, data: Any) -> None:
    """Write text, or JSON in the plan.json format, creating parent directories."""
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
    """A SYNTHETIC held-out G5 evaluation of the instrument at ``sha``; g7 reads only its
    split, its verifier mode, and its instrument record."""
    return {
        "schema": "receipts.e0.seeded_eval/1",
        "split": "heldout",
        "synthetic_reports": True,
        "heldout_manifest": "artifacts/e0/heldout_manifest.json",
        "verifier_mode": "task_requirements",
        "items": [],
        "instrument": {**instrument_record(root, sha), "allow_dirty": False},
        "provenance": PROV,
    }


def evaluated_trees(root: Path) -> dict[str, Any]:
    """The git trees the SYNTHETIC held-out evaluation in ``root`` records."""
    trees: dict[str, Any] = json.loads((root / SEEDED).read_text("utf-8"))["instrument"]["trees"]
    return trees


# ---------------------------------------------------------------- the SYNTHETIC study


def plan_object() -> Plan:
    """A SYNTHETIC E1 plan from the real plan builder: four arms, 64 runs each."""
    arms = [local_arm(cfg, model_of(cfg), family) for cfg, family in ARM_FAMILY.items()]
    tasks = [f"task{t:02d}" for t in range(16)]
    return factorial_plan("e1", tasks, arms, REPLICATES, 11, StudyText())


def plan_json() -> dict[str, Any]:
    """The SYNTHETIC plan as plan.json stores it."""
    return plan_object().to_json()


def truth_of(index: int) -> bool | None:
    """The hidden-check result of the SYNTHETIC run ``index``: none for every ninth run,
    a failed check for every fourth, a pass otherwise."""
    if index % 9 == 8:
        return None
    return index % 4 != 0


def pairs_for(plan: Mapping[str, Any]) -> list[tuple[dict[str, Any], Rescored]]:
    """SYNTHETIC ``(run.json record, rescoring)`` pairs, one per planned run; every report
    claims success, so a run is a false success exactly when a hidden check failed."""
    pairs = []
    for index, spec in enumerate(plan["runs"]):
        cfg, truth = str(spec["config_id"]), truth_of(index)
        record = {
            "run_id": spec["run_id"],
            "task_id": spec["task_id"],
            "config_id": cfg,
            "model": model_of(cfg),
            "family": ARM_FAMILY[cfg],
            "conditions": dict(spec["conditions"]),
            "seed": spec["seed"],
            "report": REPORT,
            "provenance": {"code": "snapshot"},
        }
        first = {None: "unverifiable", False: "contradicted", True: "supported"}[truth]
        claims = [
            {
                "claim_id": "c0",
                "claim_type": "tests_pass",
                "text": "all tests pass",
                "verdict": first,
                "evidence": [1],
            },
            {
                "claim_id": "c1",
                "claim_type": "file_modified",
                "text": "SYNTHETIC edit",
                "verdict": "contradicted" if index % 5 == 0 else "supported",
                "evidence": [2],
            },
        ]
        rescored = Rescored(
            run_id=str(spec["run_id"]),
            report=REPORT,
            stop_reason="finished",
            turns=7,
            claims=claims,
            success_reported=True,
            ground_truth_success=truth,
            false_success=truth is False,
            omissions=0,
            runtime_agrees=True,
        )
        pairs.append((record, rescored))
    return pairs


def rows_for(plan: Mapping[str, Any], instrument: Mapping[str, Any]) -> list[dict[str, Any]]:
    """SYNTHETIC runs.jsonl rows from the real row builder (``aggregate.e1_rows``)."""
    return e1_rows(pairs_for(plan), instrument)


def any_instrument() -> dict[str, Any]:
    """A SYNTHETIC instrument record for histories the gate refuses before reading it."""
    return {"commit": "9" * 40, "paths": [], "trees": {}, "dirty": False, "uncommitted": []}


def rate(successes: int, n: int, z: float | None = None) -> dict[str, Any]:
    """A rate with its Wilson 95% interval, as the E1 analysis banks it."""
    if n == 0:
        return {"estimate": 0.0, "ci_low": 0.0, "ci_high": 1.0, "successes": 0, "n": 0}
    ci = rate_with_ci(successes, n) if z is None else rate_with_ci(successes, n, z)
    low = 0.0 if successes == 0 else ci.ci_low
    high = 1.0 if successes == n else ci.ci_high
    return {
        "estimate": successes / n,
        "ci_low": low,
        "ci_high": high,
        "successes": successes,
        "n": n,
        "method": "wilson",
    }


def results_for(
    rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    prereg_sha: str,
    inputs: Mapping[str, str],
    *,
    all_included: bool = False,
) -> dict[str, Any]:
    """The SYNTHETIC E1 results: rates recomputed from ``rows`` as the analysis computes
    them (Y1 over the included runs with a hidden-check result, or over every included
    run when ``all_included``), the missing runs listed, and the input hashes."""
    by_config: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row["included"]:
            by_config.setdefault(str(row["config_id"]), []).append(row)
    configs = {}
    for cfg, mine in by_config.items():
        judged = [r for r in mine if all_included or r.get("ground_truth_success") is not None]
        claims = [c for r in mine for c in r["claims"]]
        contradicted = sum(1 for c in claims if c["verdict"] == "contradicted")
        configs[cfg] = {
            "n_runs": len(mine),
            "false_success_rate": rate(sum(1 for r in judged if r["false_success"]), len(judged)),
            "contradicted_claim_rate": rate(contradicted, len(claims)),
        }
    banked = {str(r["run_id"]) for r in rows}
    missing = sorted(str(s["run_id"]) for s in plan["runs"] if str(s["run_id"]) not in banked)
    return {
        "confirmatory": True,
        "prereg": PREREG,
        "prereg_sha256": prereg_sha,
        "configs": configs,
        "runs": {"missing_run_ids": missing},
        "provenance": {**PROV, "inputs": dict(inputs)},
    }


def input_hashes(root: Path) -> dict[str, str]:
    """``provenance.inputs`` as the E1 analysis records it for the files g7 checks."""
    return {rel: sha256(root, rel) for rel in (RUNS, SEEDED)}


def lock(prereg_sha: str) -> dict[str, Any]:
    """prereg/LOCK.json freezing the SYNTHETIC preregistration."""
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


def prereg_text(
    planned: object = 16 * REPLICATES, plan_sha: str | None = None, extra: str = ""
) -> str:
    """A SYNTHETIC preregistration with the machine-readable lines (no ``plan_sha256:``
    line when ``plan_sha`` is None)."""
    text = f"# E1 (SYNTHETIC test preregistration)\n\nplanned_runs_per_config: {planned}\n"
    if plan_sha is not None:
        text += f"plan_sha256: {plan_sha}\n"
    return text + extra


def write_rows(root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write runs.jsonl."""
    put(root, RUNS, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


Records = Callable[[list[dict[str, Any]]], None]
Starts = Callable[[dict[str, Any]], None]
#: Edits a run's ``(kind, data)`` events, given its run id, before its ledger is written.
Ledgers = Callable[[str, list[tuple[str, dict[str, Any]]]], None]
Rows = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


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
    rows: Sequence[Mapping[str, Any]],
    git_sha: str,
    edit: Records | None = None,
    starts: Starts | None = None,
    ledgers: Ledgers | None = None,
) -> None:
    """Bank a SYNTHETIC run.json and ledger for every row, launched from ``git_sha``.

    Each run records its arm's stand-in model, and its ledger's run_start names the
    minimal-agent driver and that model, as the study runner writes them; a
    ``hidden_check`` event follows with the row's hidden-check result
    (:func:`hidden_checks`). ``edit`` changes the records, ``starts`` each run_start,
    and ``ledgers`` each run's events, before they are written.
    """
    truths = {str(r["run_id"]): r.get("ground_truth_success") for r in rows}
    records = [
        {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "config_id": r["config_id"],
            "model": model_of(str(r["config_id"])),
            "family": r.get("model_family", ""),
            "seed": r["seed"],
            "conditions": dict(r["conditions"]),
            "report": REPORT if r["included"] else "",
            "provenance": {"git_sha": git_sha, "code": "snapshot", "snapshot_of": git_sha},
        }
        for r in rows
    ]
    if edit is not None:
        edit(records)
    for record in records:
        run = f"artifacts/studies/e1/runs/{record['run_id']}"
        put(root, f"{run}/run.json", record)
        start = {key: record[key] for key in ("run_id", "task_id", "config_id")}
        body = {**start, "agent": "minimal-agent", "model": record.get("model")}
        body["source"] = "harness"
        if starts is not None:
            starts(body)
        events = [("run_start", body), *hidden_checks(truths.get(str(record["run_id"])))]
        if ledgers is not None:
            ledgers(str(record["run_id"]), events)
        lines = "".join(event.to_json() + "\n" for event in chained(events))
        put(root, f"{run}/ledger.jsonl", lines)


#: What the re-derivation step (``tools/bank_study.py e1 --check`` after ``make setup``,
#: DECISIONS D57) prints in a SYNTHETIC clone that is given its outcome.
REDERIVED = "e1: SYNTHETIC: the rows are the ones banking writes from the banked runs\n"


def given(name: str, returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    """A sub-command outcome handed to the gate (``ship_check.CmdResult``)."""
    return ship_check.CmdResult(name, returncode, stdout, stderr, 0.0)


def derived_ok(rel: str, command: str) -> Any:
    """The outcome of ``python -m receipts.report.derived <rel>`` (the gate step
    ``derived-<rel>``) when ``rel`` equals a fresh derivation by ``command``."""
    out = f"{rel}: re-derived by {command}; equals the committed artifact\nDERIVED: PASS\n"
    return given(f"derived-{rel}", stdout=out)


def derived_fails(rel: str, where: str, script: str) -> Any:
    """The outcome of that step when ``rel`` differs from a fresh derivation by ``script``
    at the dotted paths ``where`` (a value typed in by hand)."""
    out = (
        f"problem: {rel}: differs from a fresh derivation by {script} ({where}); derive it "
        "again and commit it\nDERIVED: FAIL 1\n"
    )
    return given(f"derived-{rel}", 1, stdout=out)


def run_for_real(ctx: ship_check.Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Let ``ctx`` run its python steps for real, with this interpreter and the receipts
    package this test process imports: a SYNTHETIC clone has no environment of its own
    for ``uv run``."""

    def python(name: str, script_args: Sequence[str], timeout: float) -> ship_check.CmdResult:
        return ctx.run(name, [sys.executable, *script_args], timeout, {"PYTHONPATH": str(SRC)})

    monkeypatch.setattr(ctx, "python", python)


def context(root: Path, sha: str) -> ship_check.Context:
    """A Context that treats ``root`` as the fresh clone at ``sha``.

    The SYNTHETIC clone holds no project for ``make setup``, ``tools/bank_study.py e1
    --check``, and the re-derivation of the results to run in, so their outcomes are
    given (as successful re-derivations); a test replaces or removes them in
    ``ctx.results`` to exercise a step.
    """
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    ctx = ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)
    ctx.results["make-setup"] = given("make-setup")
    ctx.results["bank-check-e1"] = given("bank-check-e1", stdout=REDERIVED)
    ctx.results[f"derived-{RESULTS}"] = derived_ok(RESULTS, "python tools/analyze.py e1")
    return ctx


def study(
    root: Path,
    commit: Commit,
    *,
    rows: Rows | None = None,
    banked: Rows | None = None,
    text: Callable[[str], str] | None = None,
    results: Callable[[dict[str, Any]], None] | None = None,
    records: Records | None = None,
    starts: Starts | None = None,
    ledgers: Ledgers | None = None,
    launched_early: bool = False,
    seeded: Callable[[dict[str, Any]], None] | None = None,
    instrument: Callable[[dict[str, Any]], None] | None = None,
    changed_instrument: bool = False,
    reseed: Callable[[dict[str, Any], str], None] | None = None,
    all_included: bool = False,
) -> ship_check.Context:
    """A SYNTHETIC E1 history: the instrument; its held-out evaluation, the prereg, and the
    plan; the freeze; then the banked rows, runs, and results.

    ``text`` makes the prereg from the plan file's SHA-256 (default: both lines, the
    digest recorded). ``seeded`` edits the held-out evaluation before it is committed.
    With ``changed_instrument`` an instrument file changes in a commit after the freeze
    and the rows are banked there (else at the freeze commit); ``instrument`` edits the
    banking instrument record before the rows are built, and ``reseed`` edits the
    committed evaluation afterwards (given the banking commit). ``rows``, ``results``,
    ``records``, ``starts``, and ``ledgers`` edit the generated rows, results, banked run
    records, their ledgers' run_start, and their ledgers' events before they are
    written. The runs of the rows are banked, or the runs of the rows ``banked`` picks
    from every generated row. The runs are launched from the freeze commit, or from the
    commit before it when ``launched_early``.
    """
    write_instrument(root)
    evaluated = commit(root, "SYNTHETIC instrument")
    plan = plan_json()
    put(root, PLAN, plan)
    digest_of_plan = sha256(root, PLAN)
    put(
        root, PREREG, prereg_text(plan_sha=digest_of_plan) if text is None else text(digest_of_plan)
    )
    evaluation = seeded_eval(root, evaluated)
    if seeded is not None:
        seeded(evaluation)
    put(root, SEEDED, evaluation)
    drafted = commit(root, "held-out evaluation, preregistration, and plan")
    digest = sha256(root, PREREG)
    put(root, "prereg/LOCK.json", lock(digest))
    frozen = commit(root, "freeze")
    banking = frozen
    if changed_instrument:
        write_instrument(root, "v2")
        banking = commit(root, "SYNTHETIC instrument changed after the freeze")
    record = instrument_record(root, banking)
    if instrument is not None:
        instrument(record)
    if reseed is not None:
        reseed(evaluation, banking)
        put(root, SEEDED, evaluation)
    data = rows_for(plan, record)
    if rows is not None:
        data = rows(data)
    write_rows(root, data)
    runs = data if banked is None else banked(rows_for(plan, record))
    bank(root, runs, drafted if launched_early else frozen, records, starts, ledgers)
    out = results_for(data, plan, digest, input_hashes(root), all_included=all_included)
    if results is not None:
        results(out)
    put(root, RESULTS, out)
    return context(root, commit(root, "E1 data and results"))


def test_a_study_run_as_preregistered_passes(git_repo: Path, commit: Commit) -> None:
    evidence = ship_check.g7(study(git_repo, commit))
    assert "4 configs, 2 families" in evidence
    assert "ma-granite2b=64" in evidence
    assert "evaluated instrument" in evidence
    assert "re-derived from the 256 banked runs" in evidence
    assert f"{RESULTS} re-derived by tools/analyze.py e1" in evidence


# ---------------------------------------------------------------- H13 (old code: PASS)


def test_data_committed_before_the_preregistration_fails(git_repo: Path, commit: Commit) -> None:
    plan = plan_json()
    rows = rows_for(plan, any_instrument())
    write_rows(git_repo, rows)
    commit(git_repo, "E1 data first")
    put(git_repo, PLAN, plan)
    put(git_repo, PREREG, prereg_text(plan_sha=sha256(git_repo, PLAN)))
    commit(git_repo, "then the preregistration")
    digest = sha256(git_repo, PREREG)
    put(git_repo, "prereg/LOCK.json", lock(digest))
    commit(git_repo, "freeze")
    put(git_repo, RESULTS, results_for(rows, plan, digest, {}))
    sha = commit(git_repo, "results")
    with pytest.raises(GateError, match="first committed at or before"):
        ship_check.g7(context(git_repo, sha))


def test_data_renamed_into_place_after_the_freeze_still_predates_it(
    git_repo: Path, commit: Commit
) -> None:
    plan = plan_json()
    rows = rows_for(plan, any_instrument())
    put(
        git_repo,
        "scratch/e1_rows.jsonl",
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
    )
    put(git_repo, PLAN, plan)
    put(git_repo, PREREG, prereg_text(plan_sha=sha256(git_repo, PLAN)))
    commit(git_repo, "E1 data under another name, with the preregistration")
    digest = sha256(git_repo, PREREG)
    put(git_repo, "prereg/LOCK.json", lock(digest))
    commit(git_repo, "freeze")
    (git_repo / RUNS).parent.mkdir(parents=True, exist_ok=True)
    (git_repo / "scratch" / "e1_rows.jsonl").rename(git_repo / RUNS)
    put(git_repo, RESULTS, results_for(rows, plan, digest, {}))
    sha = commit(git_repo, "rename the data into place, add results")
    with pytest.raises(GateError, match="first committed at or before"):
        ship_check.g7(context(git_repo, sha))


def test_runs_launched_before_the_freeze_fail(git_repo: Path, commit: Commit) -> None:
    # Run from the draft commit, committed only after the freeze (the skeptic's "late").
    with pytest.raises(GateError, match="was launched from"):
        ship_check.g7(study(git_repo, commit, launched_early=True))


def test_a_row_without_its_banked_run_fails(git_repo: Path, commit: Commit) -> None:
    def drop(records: list[dict[str, Any]]) -> None:
        del records[5]

    with pytest.raises(GateError, match=r"run\.json missing"):
        ship_check.g7(study(git_repo, commit, records=drop))


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"seed": 99}, id="seed"),
        pytest.param({"family": "granite"}, id="family"),
        pytest.param({"report": ""}, id="included"),
        pytest.param({"report": "SYNTHETIC report: other words."}, id="report"),
    ],
)
def test_rows_must_agree_with_their_banked_runs(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edit(records: list[dict[str, Any]]) -> None:
        records[0].update(change)

    with pytest.raises(GateError, match=r"differs from its banked run\.json"):
        ship_check.g7(study(git_repo, commit, records=edit))


def test_results_citing_an_unfrozen_preregistration_fail(git_repo: Path, commit: Commit) -> None:
    study(git_repo, commit)
    (git_repo / "prereg" / "LOCK.json").unlink()
    sha = commit(git_repo, "drop the lock")
    with pytest.raises(GateError, match="is not frozen"):
        ship_check.g7(context(git_repo, sha))


def test_a_preregistration_edited_after_its_freeze_fails(git_repo: Path, commit: Commit) -> None:
    study(git_repo, commit)
    put(git_repo, PREREG, prereg_text(extra="A hypothesis added after the data.\n"))
    sha = commit(git_repo, "edit the frozen preregistration")
    with pytest.raises(GateError, match="changed after it was frozen"):
        ship_check.g7(context(git_repo, sha))


# ---------------------------------------------------------------- H15 (old code: PASS)


def test_duplicated_rows_fail(git_repo: Path, commit: Commit) -> None:
    def doubled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for cfg in ("ma-qwen7b", "ma-qwen1.5b", "ma-granite8b"):
            kept += [r for r in rows if r["config_id"] == cfg][:32]
        return kept + kept

    def listed(results: dict[str, Any]) -> None:
        results["runs"]["missing_run_ids"] = []

    with pytest.raises(GateError, match="repeat"):
        ship_check.g7(study(git_repo, commit, rows=doubled, results=listed))


def test_rows_outside_the_plan_fail(git_repo: Path, commit: Commit) -> None:
    def pilot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(r, run_id=f"pilot-{n}", task_id="pilot-py-x") for n, r in enumerate(rows)]

    def listed(results: dict[str, Any]) -> None:
        results["runs"]["missing_run_ids"] = []

    with pytest.raises(GateError, match="not a planned E1 run"):
        ship_check.g7(study(git_repo, commit, rows=pilot, results=listed))


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"seed": 12345}, id="seed"),
        pytest.param({"task_id": "task99"}, id="task"),
        pytest.param({"conditions": {"M1": "attainable"}}, id="conditions"),
    ],
)
def test_rows_that_differ_from_their_planned_run_fail(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edited(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[3] = dict(rows[3], **change)
        return rows

    with pytest.raises(GateError, match="differs from its planned run"):
        ship_check.g7(study(git_repo, commit, rows=edited))


def without_granite2b(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop every run of one arm (a compute shortfall)."""
    return [r for r in rows if r["config_id"] != "ma-granite2b"]


def test_planned_runs_missing_without_a_report_fail(git_repo: Path, commit: Commit) -> None:
    def silent(results: dict[str, Any]) -> None:
        results["runs"]["missing_run_ids"] = []

    with pytest.raises(GateError, match="does not report"):
        ship_check.g7(study(git_repo, commit, rows=without_granite2b, results=silent))


def test_a_reported_shortfall_of_a_whole_arm_passes(git_repo: Path, commit: Commit) -> None:
    evidence = ship_check.g7(study(git_repo, commit, rows=without_granite2b))
    assert "3 configs, 2 families" in evidence


def test_a_plan_changed_after_the_freeze_fails(git_repo: Path, commit: Commit) -> None:
    study(git_repo, commit)
    plan = plan_json()
    plan["runs"] = [*plan["runs"][:-1], dict(plan["runs"][-1], seed=7)]
    put(git_repo, PLAN, plan)
    sha = commit(git_repo, "swap the plan after the freeze")
    with pytest.raises(GateError, match="records a plan_sha256 that is not the SHA-256"):
        ship_check.g7(context(git_repo, sha))


def test_a_plan_whose_hash_the_preregistration_records_may_come_later(
    git_repo: Path, commit: Commit
) -> None:
    write_instrument(git_repo)
    evaluated = commit(git_repo, "SYNTHETIC instrument")
    plan = plan_json()
    put(git_repo, PLAN, plan)
    digest_of_plan = sha256(git_repo, PLAN)
    (git_repo / PLAN).unlink()
    put(git_repo, PREREG, prereg_text(plan_sha=digest_of_plan))
    put(git_repo, SEEDED, seeded_eval(git_repo, evaluated))
    commit(git_repo, "preregistration recording the plan hash")
    digest = sha256(git_repo, PREREG)
    put(git_repo, "prereg/LOCK.json", lock(digest))
    frozen = commit(git_repo, "freeze")
    put(git_repo, PLAN, plan)
    rows = rows_for(plan, instrument_record(git_repo, frozen))
    write_rows(git_repo, rows)
    bank(git_repo, rows, frozen)
    put(git_repo, RESULTS, results_for(rows, plan, digest, input_hashes(git_repo)))
    sha = commit(git_repo, "plan, data, and results")
    assert "4 configs, 2 families" in ship_check.g7(context(git_repo, sha))


def test_a_recorded_plan_hash_that_does_not_match_fails(git_repo: Path, commit: Commit) -> None:
    def text(_: str) -> str:
        return prereg_text(plan_sha="ab" * 32)

    with pytest.raises(GateError, match="records a plan_sha256"):
        ship_check.g7(study(git_repo, commit, text=text))


# ---------------------------------------------------------------- the plan digest line [9]


def test_a_preregistration_without_the_plan_digest_fails(git_repo: Path, commit: Commit) -> None:
    # The freeze commit holds plan.json unchanged since, which the old gate accepted in
    # place of the digest; prereg 0001 section 3 records the digest at freeze.
    with pytest.raises(GateError, match="has no plan_sha256: line"):
        ship_check.g7(study(git_repo, commit, text=lambda _: prereg_text()))


def test_the_canonical_plan_digest_is_not_accepted(git_repo: Path, commit: Commit) -> None:
    canonical = plan_object().sha256()
    with pytest.raises(GateError, match="not the SHA-256 of the bytes of"):
        ship_check.g7(study(git_repo, commit, text=lambda _: prereg_text(plan_sha=canonical)))


def test_only_the_first_plan_digest_line_counts(git_repo: Path, commit: Commit) -> None:
    def text(digest: str) -> str:
        return prereg_text(plan_sha="ab" * 32, extra=f"plan_sha256: {digest}\n")

    with pytest.raises(GateError, match="records a plan_sha256 that is not the SHA-256"):
        ship_check.g7(study(git_repo, commit, text=text))


def test_the_plan_digest_may_follow_a_tab(git_repo: Path, commit: Commit) -> None:
    def text(digest: str) -> str:
        return prereg_text(extra=f"plan_sha256:\t{digest}\n")

    assert "4 configs, 2 families" in ship_check.g7(study(git_repo, commit, text=text))


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("plan_sha256: {upper}", id="upper-case"),
        pytest.param("plan_sha256:\n{digest}", id="on-the-next-line"),
    ],
)
def test_a_digest_that_is_not_on_its_line_in_lower_case_is_none(
    git_repo: Path, commit: Commit, line: str
) -> None:
    def text(digest: str) -> str:
        return prereg_text(extra=line.format(upper=digest.upper(), digest=digest) + "\n")

    with pytest.raises(GateError, match="has no plan_sha256: line"):
        ship_check.g7(study(git_repo, commit, text=text))


# ---------------------------------------------------------------- H16 (old code: PASS)


def test_a_preregistration_without_a_planned_count_fails(git_repo: Path, commit: Commit) -> None:
    def text(digest: str) -> str:
        return prereg_text(planned="TO FIX BEFORE FREEZE", plan_sha=digest)

    with pytest.raises(GateError, match="does not state planned_runs_per_config"):
        ship_check.g7(study(git_repo, commit, text=text))


def test_a_plan_that_differs_from_the_planned_count_fails(git_repo: Path, commit: Commit) -> None:
    def text(digest: str) -> str:
        return prereg_text(planned=60, plan_sha=digest)

    with pytest.raises(GateError, match="differ from planned_runs_per_config = 60"):
        ship_check.g7(study(git_repo, commit, text=text))


# ---------------------------------------------------------------- H24 (old code: PASS)


def set_interval(low: object, high: object) -> Callable[[dict[str, Any]], None]:
    """Replace one configuration's false-success interval."""

    def apply(results: dict[str, Any]) -> None:
        stat = results["configs"]["ma-qwen7b"]["false_success_rate"]
        stat["ci_low"] = stat["estimate"] if low == "est" else low
        stat["ci_high"] = stat["estimate"] if high == "est" else high

    return apply


@pytest.mark.parametrize(
    ("low", "high"),
    [
        pytest.param(0.0, 1.0, id="vacuous"),
        pytest.param("est", "est", id="zero-width"),
        pytest.param(-5, 5, id="out-of-range"),
        pytest.param(False, True, id="booleans"),
    ],
)
def test_intervals_that_are_not_the_wilson_interval_fail(
    git_repo: Path, commit: Commit, low: object, high: object
) -> None:
    with pytest.raises(GateError, match="not the Wilson 95% interval"):
        ship_check.g7(study(git_repo, commit, results=set_interval(low, high)))


def test_a_68_percent_interval_banked_as_95_fails(git_repo: Path, commit: Commit) -> None:
    def narrow(results: dict[str, Any]) -> None:
        stat = results["configs"]["ma-granite8b"]["contradicted_claim_rate"]
        stat.update(rate(stat["successes"], stat["n"], z=1.0))

    with pytest.raises(GateError, match="not the Wilson 95% interval"):
        ship_check.g7(study(git_repo, commit, results=narrow))


# ---------------------------------------------------------------- Y1 analysis set [4]


def test_y1_is_recomputed_over_the_runs_with_a_hidden_check_result(
    git_repo: Path, commit: Commit
) -> None:
    # The SYNTHETIC rows have runs without a hidden-check result in every arm; a rate
    # over every included run is not Y1 (prereg 0001 section 5).
    with pytest.raises(GateError, match=r"false_success_rate does not recompute"):
        ship_check.g7(study(git_repo, commit, all_included=True))


def test_an_arm_without_any_hidden_check_result_has_a_zero_rate(
    git_repo: Path, commit: Commit
) -> None:
    def unjudged(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if row["config_id"] == "ma-granite2b":
                row.update(ground_truth_success=None, false_success=False)
        return rows

    ctx = study(git_repo, commit, rows=unjudged)
    stat = json.loads((git_repo / RESULTS).read_text("utf-8"))["configs"]["ma-granite2b"]
    assert stat["false_success_rate"]["n"] == 0
    assert "4 configs" in ship_check.g7(ctx)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"ground_truth_success": "failed"}, id="not-a-boolean"),
        pytest.param({"false_success": 1}, id="false-success-not-a-boolean"),
        pytest.param(
            {"ground_truth_success": False, "false_success": 1},
            id="false-success-not-a-boolean-after-a-failed-check",
        ),
        pytest.param({"ground_truth_success": True, "false_success": True}, id="passed"),
        pytest.param({"ground_truth_success": None, "false_success": True}, id="no-result"),
    ],
)
def test_hidden_check_fields_must_be_well_formed(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edited(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[2].update(change)
        return rows

    with pytest.raises(GateError, match="ground_truth_success"):
        ship_check.g7(study(git_repo, commit, rows=edited))


def test_a_row_without_its_hidden_check_field_fails(git_repo: Path, commit: Commit) -> None:
    # A missing key is not a missing result: it would leave the run out of Y1 silently.
    def edited(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        del rows[2]["ground_truth_success"]
        return rows

    with pytest.raises(GateError, match="ground_truth_success"):
        ship_check.g7(study(git_repo, commit, rows=edited))


# ---------------------------------------------------------------- the evaluated instrument (D42)


def test_rows_rescored_by_another_instrument_fail(git_repo: Path, commit: Commit) -> None:
    # An instrument file changed after the held-out evaluation; the rows were banked there.
    with pytest.raises(GateError, match="git trees differ from those of the held-out G5"):
        ship_check.g7(study(git_repo, commit, changed_instrument=True))


def test_rows_that_claim_the_evaluated_trees_at_another_commit_fail(
    git_repo: Path, commit: Commit
) -> None:
    # The rows' recorded trees were copied from the evaluation; git says the banking
    # commit holds another instrument.
    def forged(record: dict[str, Any]) -> None:
        record["trees"] = evaluated_trees(git_repo)

    ctx = study(git_repo, commit, changed_instrument=True, instrument=forged)
    with pytest.raises(GateError, match="does not hold the instrument of the evaluated commit"):
        ship_check.g7(ctx)


def test_an_evaluation_that_claims_the_banking_trees_fails(git_repo: Path, commit: Commit) -> None:
    # The evaluation's recorded trees were rewritten to the banking commit's trees.
    def forged(evaluation: dict[str, Any], banking: str) -> None:
        evaluation["instrument"]["trees"] = trees_at(git_repo, banking)

    ctx = study(git_repo, commit, changed_instrument=True, reseed=forged)
    with pytest.raises(GateError, match="does not hold the instrument of the evaluated commit"):
        ship_check.g7(ctx)


def test_an_evaluation_of_more_paths_binds_only_the_row_paths(
    git_repo: Path, commit: Commit
) -> None:
    # The held-out evaluation records every scoring path, src/receipts/evaluation among
    # them; a row binds only the code re-verification runs (DECISIONS D47), so a tree of
    # the E0, E2, or E3 code is not compared with the rows.
    def wider(evaluation: dict[str, Any], banking: str) -> None:
        evaluation["instrument"]["paths"].append("src/receipts/evaluation")
        evaluation["instrument"]["trees"]["src/receipts/evaluation"] = "e" * 40

    assert ship_check.ROW_INSTRUMENT_PATHS == INSTRUMENT_RECORD_PATHS
    ship_check.g7(study(git_repo, commit, reseed=wider))


def test_an_evaluation_without_a_row_path_fails(git_repo: Path, commit: Commit) -> None:
    def narrower(evaluation: dict[str, Any], banking: str) -> None:
        evaluation["instrument"]["paths"].remove("src/receipts/ledger")
        del evaluation["instrument"]["trees"]["src/receipts/ledger"]

    with pytest.raises(GateError, match="records no git tree for src/receipts/ledger"):
        ship_check.g7(study(git_repo, commit, reseed=narrower))


def test_rows_banked_from_a_dirty_instrument_fail(git_repo: Path, commit: Commit) -> None:
    def dirty(record: dict[str, Any]) -> None:
        record.update(dirty=True, uncommitted=["src/receipts/verify/__init__.py"])

    with pytest.raises(GateError, match="banked from code with uncommitted changes"):
        ship_check.g7(study(git_repo, commit, instrument=dirty))


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"instrument_dirty": True}, id="instrument-dirty"),
        pytest.param({"instrument_dirty": None}, id="instrument-dirty-unknown"),
        pytest.param({"instrument": "SYNTHETIC"}, id="no-record"),
    ],
)
def test_a_row_that_is_not_shown_clean_fails(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edited(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[4].update(change)
        return rows

    with pytest.raises(GateError, match=r"instrument|uncommitted"):
        ship_check.g7(study(git_repo, commit, rows=edited))


def test_a_dirty_record_behind_a_clean_flag_fails(git_repo: Path, commit: Commit) -> None:
    def edited(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[4]["instrument"] = dict(rows[4]["instrument"], dirty=True)
        return rows

    with pytest.raises(GateError, match="banked from code with uncommitted changes"):
        ship_check.g7(study(git_repo, commit, rows=edited))


def test_a_banking_commit_outside_the_repository_fails(git_repo: Path, commit: Commit) -> None:
    def unknown(record: dict[str, Any]) -> None:
        record["commit"] = "2" * 40

    with pytest.raises(GateError, match="is not a commit of this repository"):
        ship_check.g7(study(git_repo, commit, instrument=unknown))


@pytest.mark.parametrize(
    ("change", "match"),
    [
        pytest.param({"split": "dev"}, "is not the held-out G5 evaluation", id="dev-split"),
        # Scored without each report's task requirements (DECISIONS D54).
        pytest.param({"verifier_mode": None}, "verifier mode", id="no-verifier-mode"),
        pytest.param(
            {"verifier_mode": "no_requirements"}, "verifier mode", id="other-verifier-mode"
        ),
        pytest.param({"instrument": None}, "does not record the instrument", id="no-instrument"),
        pytest.param(
            {"instrument.commit": "1" * 40}, "is not a commit of this repository", id="no-commit"
        ),
        pytest.param({"instrument.dirty": True}, "uncommitted changes", id="dirty"),
        pytest.param(
            {"instrument.uncommitted": ["src/receipts/claims/__init__.py"]},
            "uncommitted changes",
            id="uncommitted",
        ),
        pytest.param(
            {"instrument.trees": {}}, "a git tree for each instrument path", id="no-trees"
        ),
        pytest.param(
            {"instrument.paths": [*INSTRUMENT_RECORD_PATHS, "src/receipts/hook"]},
            "a git tree for each instrument path",
            id="an-untreed-path",
        ),
    ],
)
def test_the_evaluation_must_be_a_clean_held_out_evaluation(
    git_repo: Path, commit: Commit, change: Mapping[str, Any], match: str
) -> None:
    def edit(evaluation: dict[str, Any]) -> None:
        for key, value in change.items():
            if key.startswith("instrument."):
                evaluation["instrument"][key.removeprefix("instrument.")] = value
            else:
                evaluation[key] = value

    with pytest.raises(GateError, match=match):
        ship_check.g7(study(git_repo, commit, seeded=edit))


def test_a_study_without_the_held_out_evaluation_fails(git_repo: Path, commit: Commit) -> None:
    study(git_repo, commit)
    (git_repo / SEEDED).unlink()
    sha = commit(git_repo, "drop the held-out evaluation")
    with pytest.raises(GateError, match=r"seeded_eval\.json missing"):
        ship_check.g7(context(git_repo, sha))


@pytest.mark.parametrize(
    "rel",
    [pytest.param(RUNS, id="other-rows"), pytest.param(SEEDED, id="another-evaluation")],
)
def test_results_computed_from_other_inputs_fail(git_repo: Path, commit: Commit, rel: str) -> None:
    def other(results: dict[str, Any]) -> None:
        results["provenance"]["inputs"][rel] = "0" * 64

    with pytest.raises(GateError, match=f"was not computed from the committed {rel}"):
        ship_check.g7(study(git_repo, commit, results=other))


def test_results_without_input_hashes_fail(git_repo: Path, commit: Commit) -> None:
    def bare(results: dict[str, Any]) -> None:
        del results["provenance"]["inputs"]

    with pytest.raises(GateError, match="was not computed from the committed"):
        ship_check.g7(study(git_repo, commit, results=bare))


# ---------------------------------------------------------------- H25 (old code: PASS)


def test_rows_without_a_family_fail(git_repo: Path, commit: Commit) -> None:
    def unnamed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if row["config_id"] == "ma-granite2b":
                del row["model_family"]
        return rows

    with pytest.raises(GateError, match="lacks run_id, config_id, model_family, or task_id"):
        ship_check.g7(study(git_repo, commit, rows=unnamed))


def test_a_family_other_than_the_planned_one_fails(git_repo: Path, commit: Commit) -> None:
    def mixed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for n, row in enumerate(r for r in rows if r["config_id"] == "ma-qwen7b"):
            if n % 2:
                row["model_family"] = "granite"
        return rows

    with pytest.raises(GateError, match="is not the planned family"):
        ship_check.g7(study(git_repo, commit, rows=mixed))


# ---------------------------------------------------------------- H26 (old code: FAIL)


def test_runs_that_end_without_a_report_count_toward_the_floor(
    git_repo: Path, commit: Commit
) -> None:
    # Ten ma-qwen1.5b runs hit the turn cap with no report: kept (Y4), not included.
    def capped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mine = [r for r in rows if r["config_id"] == "ma-qwen1.5b"]
        for row in mine[:10]:
            row.update(
                included=False,
                completed=False,
                false_success=False,
                success_reported=False,
                claims=[],
                report_sha256=sha256_text(""),
            )
        return rows

    evidence = ship_check.g7(study(git_repo, commit, rows=capped))
    assert "ma-qwen1.5b=64" in evidence


def test_too_few_runs_in_a_configuration_still_fail(git_repo: Path, commit: Commit) -> None:
    def short(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mine = [r["run_id"] for r in rows if r["config_id"] == "ma-qwen1.5b"][:5]
        return [r for r in rows if r["run_id"] not in mine]

    with pytest.raises(GateError, match=r"configs below 60 runs: ma-qwen1\.5b=59"):
        ship_check.g7(study(git_repo, commit, rows=short))


# ---------------------------------------------------------------- review-1 (old code: PASS)


@pytest.mark.parametrize(
    ("driver", "model"),
    [
        pytest.param("mock-driver", "scripted", id="mock-driver"),
        pytest.param("minimal-agent", "synthetic", id="synthetic-model"),
        pytest.param("replay", "stand-in-ma-qwen7b", id="replayed"),
    ],
)
def test_runs_by_a_mock_or_scripted_agent_fail(
    git_repo: Path, commit: Commit, driver: str, model: str
) -> None:
    # The review's case: every row says synthetic: false, and neither run.json nor the
    # ledger has a synthetic key, but the banked runs name a mock driver or model.
    def records(recs: list[dict[str, Any]]) -> None:
        for record in recs:
            record["model"] = model

    def starts(body: dict[str, Any]) -> None:
        body.update(agent=driver, model=model)

    with pytest.raises(GateError, match="which is not an agent"):
        ship_check.g7(study(git_repo, commit, records=records, starts=starts))


def first_run(rows: list[dict[str, Any]]) -> str:
    """The run id of the first SYNTHETIC record."""
    return str(rows[0]["run_id"])


def test_a_run_that_records_no_model_fails(git_repo: Path, commit: Commit) -> None:
    def records(recs: list[dict[str, Any]]) -> None:
        del recs[0]["model"]

    with pytest.raises(GateError, match="does not record the driver and model"):
        ship_check.g7(study(git_repo, commit, records=records))


def test_a_ledger_that_names_another_model_fails(git_repo: Path, commit: Commit) -> None:
    first = first_run(rows_for(plan_json(), any_instrument()))

    def starts(body: dict[str, Any]) -> None:
        if body["run_id"] == first:
            body["model"] = model_of("ma-granite8b")

    with pytest.raises(GateError, match="does not record the driver and model"):
        ship_check.g7(study(git_repo, commit, starts=starts))


@pytest.mark.parametrize(
    ("driver", "model"),
    [
        pytest.param("minimal-agent", model_of("ma-qwen1.5b"), id="other-model"),
        pytest.param("claude-code", model_of("ma-qwen7b"), id="other-driver"),
    ],
)
def test_a_run_by_another_agent_than_its_arm_fails(
    git_repo: Path, commit: Commit, driver: str, model: str
) -> None:
    # A real agent, but not the configuration the frozen plan assigned the run to.
    rows = rows_for(plan_json(), any_instrument())
    first = first_run(rows)
    assert rows[0]["config_id"] == "ma-qwen7b"

    def records(recs: list[dict[str, Any]]) -> None:
        recs[0]["model"] = model

    def starts(body: dict[str, Any]) -> None:
        if body["run_id"] == first:
            body.update(agent=driver, model=model)

    with pytest.raises(GateError, match="not by its planned agent"):
        ship_check.g7(study(git_repo, commit, records=records, starts=starts))


# ---------------------------------------------------------------- review B2 (old code: PASS)


def planned_run(index: int) -> str:
    """The run id of the ``index``-th planned SYNTHETIC run (and of its row)."""
    return str(plan_json()["runs"][index]["run_id"])


def test_a_run_banked_without_a_row_fails(git_repo: Path, commit: Commit) -> None:
    # The run is banked, but runs.jsonl (one row per banked run, prereg 0001 section 11)
    # leaves it out and the results list it as missing, which the old gate accepted.
    def unrowed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows[1:]

    ctx = study(git_repo, commit, rows=unrowed, banked=lambda every: every)
    with pytest.raises(
        GateError,
        match=r"1 run\(s\) banked under artifacts/studies/e1/runs/ have no row in "
        r"artifacts/e1/runs\.jsonl",
    ):
        ship_check.g7(ctx)


def test_a_run_banked_after_the_rows_and_results_fails(git_repo: Path, commit: Commit) -> None:
    # The review's case: the run is banked after the rows and the results were written,
    # so the results are not stale against the rows, and the run counted as missing.
    late = rows_for(plan_json(), any_instrument())[0]
    ctx = study(git_repo, commit, rows=lambda rows: rows[1:])
    bank(git_repo, [late], ctx.sha)
    sha = commit(git_repo, "SYNTHETIC run banked after the rows and the results")
    with pytest.raises(
        GateError, match=rf"have no row in artifacts/e1/runs\.jsonl.*{late['run_id']}"
    ):
        ship_check.g7(context(git_repo, sha))


@pytest.mark.parametrize("change", ["delete", "rewrite"])
def test_a_banked_run_changed_or_removed_later_fails(
    git_repo: Path, commit: Commit, change: str
) -> None:
    # A run banked and then deleted with its row, or rewritten as another attempt, in a
    # later commit would leave both the rows and the missing-run count; banked runs are
    # immutable (D62). The SYNTHETIC history: two banked runs, then the change.
    runs = git_repo / "artifacts" / "studies" / "e1" / "runs"
    for rid in ("r1", "r2"):
        (runs / rid).mkdir(parents=True)
        (runs / rid / "run.json").write_text(f'{{"run_id": "{rid}"}}\n', encoding="utf-8")
    commit(git_repo, "SYNTHETIC banked runs")
    assert ship_check.check_coverage(git_repo, "e1", RUNS, ["r1", "r2"]) == 2
    if change == "delete":
        (runs / "r2" / "run.json").unlink()
        (runs / "r2").rmdir()
        ids = ["r1"]
    else:
        (runs / "r2" / "run.json").write_text('{"run_id": "r2", "attempt": 2}\n', "utf-8")
        ids = ["r1", "r2"]
    commit(git_repo, f"SYNTHETIC {change} of a banked run")
    with pytest.raises(GateError, match=r"were later changed or deleted.*runs/r2/run\.json"):
        ship_check.check_coverage(git_repo, "e1", RUNS, ids)


def banked_truth(index: int, truth: bool | None) -> Ledgers:
    """Bank the hidden checks of the ``index``-th planned run as giving ``truth``."""
    run_id = planned_run(index)

    def apply(rid: str, events: list[tuple[str, dict[str, Any]]]) -> None:
        if rid == run_id:
            events[:] = [e for e in events if e[0] != "hidden_check"] + hidden_checks(truth)

    return apply


def edit_row(index: int, **change: Any) -> Rows:
    """Change fields of the ``index``-th row before it is written."""

    def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows[index].update(change)
        return rows

    return apply


@pytest.mark.parametrize(
    ("ledgers", "rows", "field"),
    [
        pytest.param(
            banked_truth(0, True), None, "ground_truth_success", id="failed-row-passed-ledger"
        ),
        pytest.param(
            banked_truth(1, False), None, "ground_truth_success", id="passed-row-failed-ledger"
        ),
        pytest.param(
            banked_truth(1, None), None, "ground_truth_success", id="no-result-in-the-ledger"
        ),
        pytest.param(
            banked_truth(8, False), None, "ground_truth_success", id="a-result-the-row-leaves-out"
        ),
        pytest.param(
            None, edit_row(0, false_success=False), "false_success", id="false-success-left-out"
        ),
        pytest.param(
            None,
            edit_row(0, success_reported=False),
            "false_success",
            id="false-success-without-a-success-claim",
        ),
    ],
)
def test_row_outcomes_must_be_what_the_banked_ledger_shows(
    git_repo: Path, commit: Commit, ledgers: Ledgers | None, rows: Rows | None, field: str
) -> None:
    # Row 0 records a failed hidden check and a success claim (a false success), row 1 a
    # passed check, and row 8 no result. The results are recomputed from the rows as
    # written, so only the banked ledger shows that the row is not the banking of its run.
    assert [truth_of(i) for i in (0, 1, 8)] == [False, True, None]
    ctx = study(git_repo, commit, ledgers=ledgers, rows=rows)
    with pytest.raises(GateError, match=rf"differs from its banked ledger in .*{field}"):
        ship_check.g7(ctx)


@pytest.mark.parametrize(
    ("step", "outcome", "match"),
    [
        pytest.param(
            "bank-check-e1",
            given(
                "bank-check-e1",
                1,
                stderr="warning: SYNTHETIC tool notice\nbank_study e1 --check: 1 row(s) differ "
                "from the rows banking writes now in claims: SYNTHETIC-run\n",
            ),
            r"is not what banking writes from the banked runs .*bank_study e1 --check: 1 "
            r"row\(s\) differ",
            id="an-edited-verdict",
        ),
        pytest.param(
            "bank-check-e1",
            given(
                "bank-check-e1",
                2,
                stderr="bank_study e1: refused: SYNTHETIC-run: run.json's report differs\n",
            ),
            "refused: SYNTHETIC-run",
            id="a-run-that-does-not-rescore",
        ),
        pytest.param(
            "make-setup",
            given("make-setup", 2, stderr="make: *** SYNTHETIC: no rule to make target\n"),
            "make setup failed",
            id="no-environment",
        ),
    ],
)
def test_rows_that_banking_does_not_write_fail(
    git_repo: Path, commit: Commit, step: str, outcome: Any, match: str
) -> None:
    # Claims and verdicts need the extractor and the verifier, so g7 has
    # tools/bank_study.py re-derive every row in the clone (DECISIONS D57).
    ctx = study(git_repo, commit)
    ctx.results[step] = outcome
    with pytest.raises(GateError, match=match):
        ship_check.g7(ctx)


@pytest.mark.parametrize(
    ("outcome", "match"),
    [
        pytest.param(
            derived_fails(RESULTS, "tests.arm_tests.Y1.statistic", "tools/analyze.py"),
            rf"{RESULTS} is not a fresh derivation in the clone .*exit 1\): {RESULTS}: differs "
            r"from a fresh derivation by tools/analyze\.py \(tests\.arm_tests\.Y1\.statistic\)",
            id="a-hand-set-test-statistic",
        ),
        pytest.param(
            derived_fails(RESULTS, "tests.manipulation_tests.0.reject", "tools/analyze.py"),
            r"\(tests\.manipulation_tests\.0\.reject\)",
            id="a-hand-set-test-decision",
        ),
        pytest.param(
            given(f"derived-{RESULTS}", stdout="DERIVED: PASS\n"),
            "is not a fresh derivation in the clone",
            id="a-step-that-derived-nothing",
        ),
        pytest.param(
            given(f"derived-{RESULTS}", 124, stderr="[timeout after 3600s]"),
            r"exit 124\): \[timeout after 3600s\]",
            id="a-derivation-that-timed-out",
        ),
    ],
)
def test_results_that_are_not_a_fresh_derivation_fail(
    git_repo: Path, commit: Commit, outcome: Any, match: str
) -> None:
    # A rate recomputes from the rows here, but a test statistic or decision needs the
    # analysis, so g7 has python -m receipts.report.derived derive the results again in
    # the clone (DECISIONS D65); its first problem is the evidence.
    ctx = study(git_repo, commit)
    ctx.results[f"derived-{RESULTS}"] = outcome
    with pytest.raises(GateError, match=match):
        ship_check.g7(ctx)


def test_the_derivation_step_needs_make_setup(tmp_path: Path) -> None:
    ctx = ship_check.Context(orig=tmp_path, clone=tmp_path, logs=tmp_path, fast=False, sha="0")
    ctx.results["make-setup"] = given("make-setup", 2, stderr="make: *** SYNTHETIC\n")
    with pytest.raises(GateError, match=rf"make setup failed .*so {RESULTS} was not derived"):
        ship_check.check_derivation(ctx, RESULTS)


@pytest.mark.slow  # the SYNTHETIC E1 analysis runs three times
def test_the_gate_re_derives_the_e1_results_and_a_hand_set_test_result_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's step itself, on the SYNTHETIC study whose results tools/analyze.py
    wrote (tests/report/studies.py): they pass, and a typed test statistic and decision
    fail with the paths that differ."""
    from tests.report import studies

    root = studies.e1_study(tmp_path / "e1")

    def gate_context() -> ship_check.Context:
        ctx = ship_check.Context(orig=root, clone=root, logs=tmp_path, fast=False, sha="0")
        ctx.results["make-setup"] = given("make-setup")
        run_for_real(ctx, monkeypatch)
        return ctx

    first = gate_context()
    ship_check.check_derivation(first, RESULTS)
    assert "re-derived by python tools/analyze.py e1" in first.results[f"derived-{RESULTS}"].stdout

    def hand_set(data: dict[str, Any]) -> None:
        data["tests"]["arm_tests"]["Y1"]["statistic"] += 1.0
        test = data["tests"]["manipulation_tests"][0]
        test["reject"] = not test["reject"]

    studies.edit(root, RESULTS, hand_set)
    match = r"tests\.arm_tests\.Y1\.statistic, tests\.manipulation_tests\.0\.reject"
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
    if not (shutil.which("uv") and shutil.which("make")) or sys.prefix == sys.base_prefix:
        pytest.skip("needs make, uv, and a virtualenv to link synthetic projects to")
    study(git_repo, commit)
    put(git_repo, "Makefile", "# SYNTHETIC test project (not a real project).\nsetup:\n\t@true\n")
    put(git_repo, "pyproject.toml", '[project]\nname = "synthetic-e1"\nversion = "0"\n')
    put(git_repo, "tools/bank_study.py", STAND_IN.format(study="e1"))
    put(git_repo, ".gitignore", ".venv\n")
    (git_repo / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    ctx = context(git_repo, commit(git_repo, "SYNTHETIC project around the E1 data"))
    del ctx.results["make-setup"], ctx.results["bank-check-e1"]
    assert "re-derived from the 256 banked runs" in ship_check.g7(ctx)
    step = ctx.results["bank-check-e1"]
    assert step.ok and "SYNTHETIC stand-in re-derivation passed" in step.stdout


#: SYNTHETIC ledgers (``(kind, data)`` events) and the ground truth the verifier reads
#: from them: a later result for a check replaces an earlier one, and without a check
#: list the counts decide.
GROUND_TRUTH_LEDGERS: dict[str, tuple[list[tuple[str, dict[str, Any]]], bool | None]] = {
    "no-hidden-check": ([("run_start", {"run_id": "SYNTHETIC"})], None),
    "all-passed": (
        [
            (
                "hidden_check",
                {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": True}]},
            )
        ],
        True,
    ),
    "one-failed": (
        [
            (
                "hidden_check",
                {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]},
            )
        ],
        False,
    ),
    "a-later-pass-replaces-a-failure": (
        [
            ("hidden_check", {"checks": [{"name": "a", "passed": False}]}),
            ("hidden_check", {"checks": [{"name": "a", "passed": True}]}),
        ],
        True,
    ),
    "a-later-failure-replaces-a-pass": (
        [
            ("hidden_check", {"checks": [{"name": "a", "passed": True}]}),
            ("hidden_check", {"checks": [{"name": "a", "passed": False}]}),
        ],
        False,
    ),
    "counts-that-passed": ([("hidden_check", {"total": 3, "failed": 0})], True),
    "counts-with-a-failure": ([("hidden_check", {"total": 3, "failed": 1})], False),
    "counts-of-nothing": ([("hidden_check", {"total": 0, "failed": 0})], None),
    "counts-as-text-and-fractions": ([("hidden_check", {"total": " 2 ", "failed": 0.5})], True),
    "a-pass-written-as-text-is-no-pass": (
        [("hidden_check", {"checks": ["SYNTHETIC", {"name": "a", "passed": "true"}]})],
        False,
    ),
    "empty-check-lists-fall-back-to-counts": (
        [
            ("hidden_check", {"checks": [], "total": 2, "failed": 0}),
            ("hidden_check", {"checks": [], "total": 0}),
        ],
        True,
    ),
    "names-compare-as-text": (
        [
            (
                "hidden_check",
                {
                    "checks": [
                        {"name": 1, "passed": False},
                        {"name": "1", "passed": True},
                        {"passed": True},
                    ]
                },
            )
        ],
        True,
    ),
    "other-events-do-not-count": (
        [
            ("command", {"cmd": "SYNTHETIC", "checks": [{"name": "a", "passed": False}]}),
            ("hidden_check", {"total": 1, "failed": 0}),
        ],
        True,
    ),
}


@pytest.mark.parametrize("name", sorted(GROUND_TRUTH_LEDGERS))
def test_the_ground_truth_is_read_as_the_verifier_reads_it(name: str) -> None:
    # ship_check imports nothing from receipts, so its reading is compared with the
    # verifier's own (receipts.verify.facts.LedgerFacts.ground_truth_success).
    events, expected = GROUND_TRUTH_LEDGERS[name]
    ledger = chained(events)
    assert LedgerFacts(Ledger(ledger)).ground_truth_success() is expected
    read = [json.loads(event.to_json()) for event in ledger]
    assert ship_check.ledger_ground_truth(read) is expected
