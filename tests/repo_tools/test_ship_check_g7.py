"""Gate G7 of tools/ship_check.py on a synthetic E1 history (H13, H15, H16, H24 to H26,
and review-1 of the harness review round).

Every preregistration, plan, run row, and result here is SYNTHETIC, made up only to
exercise ``ship_check.g7`` in throwaway git repositories. Rows are marked
``synthetic: false`` only so the gate treats them as real runs, the arms' models are
stand-in names, and the "results" are recomputed from those rows; nothing here is a
model result or a real-world result.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.analysis.rates import rate_with_ci
from receipts.ledger.events import GENESIS, Event
from receipts.study.plan import factorial_plan, local_arm
from receipts.study.spec import StudyText

Commit = Callable[[Path, str], str]
GateError = ship_check.GateError

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


def plan_json() -> dict[str, Any]:
    """A SYNTHETIC E1 plan from the real plan builder: four arms, 64 runs each."""
    arms = [local_arm(cfg, model_of(cfg), family) for cfg, family in ARM_FAMILY.items()]
    tasks = [f"task{t:02d}" for t in range(16)]
    return factorial_plan("e1", tasks, arms, REPLICATES, 11, StudyText()).to_json()


def rows_for(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """SYNTHETIC runs.jsonl rows, one per planned run, every one with a report."""
    rows = []
    for i, spec in enumerate(plan["runs"]):
        cfg = str(spec["config_id"])
        rows.append(
            {
                "run_id": spec["run_id"],
                "config_id": cfg,
                "model_family": ARM_FAMILY[cfg],
                "task_id": spec["task_id"],
                "conditions": dict(spec["conditions"]),
                "seed": spec["seed"],
                "synthetic": False,
                "included": True,
                "completed": True,
                "false_success": i % 4 == 0,
                "claims": [
                    {"claim_id": "c0", "claim_type": "tests_pass", "verdict": "supported"},
                    {
                        "claim_id": "c1",
                        "claim_type": "file_modified",
                        "verdict": "contradicted" if i % 5 == 0 else "supported",
                    },
                ],
            }
        )
    return rows


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
    rows: Sequence[Mapping[str, Any]], plan: Mapping[str, Any], prereg_sha: str
) -> dict[str, Any]:
    """The SYNTHETIC E1 results: rates recomputed from ``rows``, missing runs listed."""
    by_config: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row["included"]:
            by_config.setdefault(str(row["config_id"]), []).append(row)
    configs = {}
    for cfg, mine in by_config.items():
        claims = [c for r in mine for c in r["claims"]]
        contradicted = sum(1 for c in claims if c["verdict"] == "contradicted")
        configs[cfg] = {
            "n_runs": len(mine),
            "false_success_rate": rate(sum(1 for r in mine if r["false_success"]), len(mine)),
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
        "provenance": PROV,
    }


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


def prereg_text(planned: object = 16 * REPLICATES, extra: str = "") -> str:
    """A SYNTHETIC preregistration with the machine-readable planned run count."""
    return f"# E1 (SYNTHETIC test preregistration)\n\nplanned_runs_per_config: {planned}\n{extra}"


def write_rows(root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write runs.jsonl."""
    put(root, RUNS, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


Records = Callable[[list[dict[str, Any]]], None]
Starts = Callable[[dict[str, Any]], None]


def bank(
    root: Path,
    rows: Sequence[Mapping[str, Any]],
    git_sha: str,
    edit: Records | None = None,
    starts: Starts | None = None,
) -> None:
    """Bank a SYNTHETIC run.json and ledger for every row, launched from ``git_sha``.

    Each run records its arm's stand-in model, and its ledger's run_start names the
    minimal-agent driver and that model, as the study runner writes them. ``edit``
    changes the records, and ``starts`` each run_start, before they are written.
    """
    records = [
        {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "config_id": r["config_id"],
            "model": model_of(str(r["config_id"])),
            "family": r.get("model_family", ""),
            "seed": r["seed"],
            "conditions": dict(r["conditions"]),
            "report": "SYNTHETIC report: all tests pass." if r["included"] else "",
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
        event = Event(
            0,
            1.0,
            "run_start",
            body,
            GENESIS,
            Event.compute_hash(0, 1.0, "run_start", body, GENESIS),
        )
        put(root, f"{run}/ledger.jsonl", event.to_json() + "\n")


def context(root: Path, sha: str) -> ship_check.Context:
    """A Context that treats ``root`` as the fresh clone at ``sha``."""
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)


def study(
    root: Path,
    commit: Commit,
    *,
    rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    text: str | None = None,
    results: Callable[[dict[str, Any]], None] | None = None,
    records: Records | None = None,
    starts: Starts | None = None,
    launched_early: bool = False,
) -> ship_check.Context:
    """A SYNTHETIC E1 history: prereg and plan, then the freeze, then data and results.

    ``rows``, ``results``, ``records``, and ``starts`` edit the generated rows, results,
    banked run records, and their ledgers' run_start before they are written. The runs
    are launched from the freeze commit, or from the commit before it when
    ``launched_early``.
    """
    plan = plan_json()
    put(root, PLAN, plan)
    put(root, PREREG, prereg_text() if text is None else text)
    drafted = commit(root, "preregistration and plan")
    digest = sha256(root, PREREG)
    put(root, "prereg/LOCK.json", lock(digest))
    frozen = commit(root, "freeze")
    data = rows_for(plan) if rows is None else rows(rows_for(plan))
    write_rows(root, data)
    bank(root, data, drafted if launched_early else frozen, records, starts)
    out = results_for(data, plan, digest)
    if results is not None:
        results(out)
    put(root, RESULTS, out)
    return context(root, commit(root, "E1 data and results"))


def test_a_study_run_as_preregistered_passes(git_repo: Path, commit: Commit) -> None:
    evidence = ship_check.g7(study(git_repo, commit))
    assert "4 configs, 2 families" in evidence
    assert "ma-granite2b=64" in evidence


# ---------------------------------------------------------------- H13 (old code: PASS)


def test_data_committed_before_the_preregistration_fails(git_repo: Path, commit: Commit) -> None:
    plan = plan_json()
    rows = rows_for(plan)
    write_rows(git_repo, rows)
    commit(git_repo, "E1 data first")
    put(git_repo, PLAN, plan)
    put(git_repo, PREREG, prereg_text())
    commit(git_repo, "then the preregistration")
    digest = sha256(git_repo, PREREG)
    put(git_repo, "prereg/LOCK.json", lock(digest))
    commit(git_repo, "freeze")
    put(git_repo, RESULTS, results_for(rows, plan, digest))
    sha = commit(git_repo, "results")
    with pytest.raises(GateError, match="first committed at or before"):
        ship_check.g7(context(git_repo, sha))


def test_data_renamed_into_place_after_the_freeze_still_predates_it(
    git_repo: Path, commit: Commit
) -> None:
    plan = plan_json()
    rows = rows_for(plan)
    put(
        git_repo,
        "scratch/e1_rows.jsonl",
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
    )
    put(git_repo, PLAN, plan)
    put(git_repo, PREREG, prereg_text())
    commit(git_repo, "E1 data under another name, with the preregistration")
    digest = sha256(git_repo, PREREG)
    put(git_repo, "prereg/LOCK.json", lock(digest))
    commit(git_repo, "freeze")
    (git_repo / RUNS).parent.mkdir(parents=True, exist_ok=True)
    (git_repo / "scratch" / "e1_rows.jsonl").rename(git_repo / RUNS)
    put(git_repo, RESULTS, results_for(rows, plan, digest))
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
    with pytest.raises(GateError, match="is not the plan frozen with"):
        ship_check.g7(context(git_repo, sha))


def test_a_plan_whose_hash_the_preregistration_records_may_come_later(
    git_repo: Path, commit: Commit
) -> None:
    plan = plan_json()
    put(git_repo, PLAN, plan)
    digest_of_plan = sha256(git_repo, PLAN)
    (git_repo / PLAN).unlink()
    put(git_repo, PREREG, prereg_text(extra=f"plan_sha256: {digest_of_plan}\n"))
    commit(git_repo, "preregistration recording the plan hash")
    digest = sha256(git_repo, PREREG)
    put(git_repo, "prereg/LOCK.json", lock(digest))
    frozen = commit(git_repo, "freeze")
    put(git_repo, PLAN, plan)
    rows = rows_for(plan)
    write_rows(git_repo, rows)
    bank(git_repo, rows, frozen)
    put(git_repo, RESULTS, results_for(rows, plan, digest))
    sha = commit(git_repo, "plan, data, and results")
    assert "4 configs, 2 families" in ship_check.g7(context(git_repo, sha))


def test_a_recorded_plan_hash_that_does_not_match_fails(git_repo: Path, commit: Commit) -> None:
    text = prereg_text(extra=f"plan_sha256: {'ab' * 32}\n")
    with pytest.raises(GateError, match="records a plan_sha256"):
        ship_check.g7(study(git_repo, commit, text=text))


# ---------------------------------------------------------------- H16 (old code: PASS)


def test_a_preregistration_without_a_planned_count_fails(git_repo: Path, commit: Commit) -> None:
    text = prereg_text(planned="TO FIX BEFORE FREEZE")
    with pytest.raises(GateError, match="does not state planned_runs_per_config"):
        ship_check.g7(study(git_repo, commit, text=text))


def test_a_plan_that_differs_from_the_planned_count_fails(git_repo: Path, commit: Commit) -> None:
    with pytest.raises(GateError, match="differ from planned_runs_per_config = 60"):
        ship_check.g7(study(git_repo, commit, text=prereg_text(planned=60)))


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
            row.update(included=False, completed=False, false_success=False, claims=[])
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
    first = first_run(rows_for(plan_json()))

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
    rows = rows_for(plan_json())
    first = first_run(rows)
    assert rows[0]["config_id"] == "ma-qwen7b"

    def records(recs: list[dict[str, Any]]) -> None:
        recs[0]["model"] = model

    def starts(body: dict[str, Any]) -> None:
        if body["run_id"] == first:
            body.update(agent=driver, model=model)

    with pytest.raises(GateError, match="not by its planned agent"):
        ship_check.g7(study(git_repo, commit, records=records, starts=starts))
