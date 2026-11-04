"""Gate G9 of tools/ship_check.py on a synthetic E4 study and hook (H18, H28, H29, and
review-1 and review-2 of the harness review round).

Every plan, run row, result, latency sample, hook module, and demo transcript here is
SYNTHETIC, made up only to exercise ``ship_check.g9`` in throwaway git repositories.
E4 rows are marked ``synthetic: false`` only so the gate treats them as real runs, and
the arms' models are stand-in names; nothing here is a model result or a real-world
result. The demo script prints fixed text.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.ledger.events import GENESIS, Event

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


def model_of(config_id: str) -> str:
    """The stand-in model name of a SYNTHETIC arm."""
    return f"stand-in-{config_id}"


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


def e4_rows(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """SYNTHETIC E4 rows, one per planned run."""
    rows = []
    for n, spec in enumerate(plan["runs"]):
        rows.append(
            {
                "run_id": spec["run_id"],
                "task_id": spec["task_id"],
                "config_id": spec["config_id"],
                "mitigation": spec["mitigation"],
                "conditions": dict(spec["conditions"]),
                "seed": spec["seed"],
                "synthetic": False,
                "has_report": n % 7 != 0,
                "z1_false_claim": n % 3 == 0,
            }
        )
    return rows


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


def e4_results(rows: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    """SYNTHETIC artifacts/e4/results.json."""
    data: dict[str, Any] = {
        "confirmatory": False,
        "prereg": "prereg/0002-e4-mitigation.md",
        "prereg_sha256": "0" * 64,
        "tasks": sorted({str(r["task_id"]) for r in rows}),
        "rows": rows,
        "outcomes": outcomes(rows),
        "provenance": PROV,
    }
    data.update(over)
    return data


Records = Callable[[list[dict[str, Any]]], None]
Starts = Callable[[dict[str, Any]], None]


def bank(
    root: Path,
    rows: list[dict[str, Any]],
    edit: Records | None = None,
    starts: Starts | None = None,
) -> None:
    """Bank a SYNTHETIC run.json and ledger for every E4 row, each recording its arm's
    stand-in model and the minimal-agent driver (``edit`` changes the records and
    ``starts`` each ledger's run_start)."""
    records = [
        {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "config_id": r["config_id"],
            "model": model_of(str(r["config_id"])),
            "mitigation": r["mitigation"],
            "seed": r["seed"],
            "conditions": dict(r["conditions"]),
            "report": "SYNTHETIC report" if r["has_report"] else "",
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
        digest = Event.compute_hash(0, 1.0, "run_start", body, GENESIS)
        put(
            root,
            f"{run}/ledger.jsonl",
            Event(0, 1.0, "run_start", body, GENESIS, digest).to_json() + "\n",
        )


def project(
    root: Path,
    commit: Commit,
    *,
    results: Callable[[dict[str, Any]], None] | None = None,
    rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    records: Records | None = None,
    starts: Starts | None = None,
    mitigations: tuple[str, ...] = MITIGATIONS,
    target: str = "receipts.hook.__main__:main",
    hook_doc: str = HOOK_DOC,
    header: str = "generated by tools/hook_demo.py",
    transcript: str = DEMO_TEXT,
    sleep: float = 0.0,
    extra: Mapping[str, str] | None = None,
) -> ship_check.Context:
    """Write and commit a SYNTHETIC G9 project; ``results``, ``rows``, ``records``, and
    ``starts`` edit the E4 data, and ``mitigations`` are the arms its plan compares."""
    for task in E1_TASKS + E4_TASKS:
        put(root, f"bench/tasks/{task}/task.toml", f'id = "{task}"\n')
    e1_rows = [{"run_id": f"e1-{n:03d}", "task_id": t} for n, t in enumerate(E1_TASKS)]
    put(root, "artifacts/e1/runs.jsonl", "".join(json.dumps(r) + "\n" for r in e1_rows))
    put(root, "artifacts/studies/e1/plan.json", e1_plan())
    plan = e4_plan(mitigations)
    put(root, "artifacts/studies/e4/plan.json", plan)
    data = e4_rows(plan) if rows is None else rows(e4_rows(plan))
    bank(root, data, records, starts)
    out = e4_results(data)
    if results is not None:
        results(out)
    put(root, "artifacts/e4/results.json", out)
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
    for rel, text in (extra or {}).items():
        put(root, rel, text)
    venv = root / ".venv"
    if not venv.exists():
        venv.symlink_to(sys.prefix, target_is_directory=True)
    sha = commit(root, "SYNTHETIC G9 project")
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)


def needs_runner() -> None:
    """Skip when the demo script cannot be re-run offline here."""
    if not (shutil.which("uv") and shutil.which("make")) or sys.prefix == sys.base_prefix:
        pytest.skip("needs make, uv, and a virtualenv to link synthetic projects to")
    if ship_check.network_isolation() is None:
        pytest.skip("no working network isolation (unshare -rn, bwrap, sandbox-exec)")


def test_a_complete_mitigation_package_passes(git_repo: Path, commit: Commit) -> None:
    needs_runner()
    evidence = ship_check.g9(project(git_repo, commit))
    assert "E4 on 2 held-out tasks" in evidence and "demo transcript reproduces" in evidence


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


def retask(task: str) -> Callable[[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Move every run of py-e4-delta onto ``task`` (rows and plan disagree then)."""

    def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(r, task_id=task) if r["task_id"] == "py-e4-delta" else r for r in rows]

    return apply


def test_runs_on_an_e1_task_behind_a_held_out_task_list_fail(
    git_repo: Path, commit: Commit
) -> None:
    # The runs used an E1 task; the reported task list still names held-out tasks.
    ctx = project(git_repo, commit, rows=retask("py-e1-alpha"), results=set_tasks(list(E4_TASKS)))
    with pytest.raises(GateError, match="differs from its planned run"):
        ship_check.g9(ctx)


def test_a_plan_that_puts_e4_runs_on_an_e1_task_fails(git_repo: Path, commit: Commit) -> None:
    plan = e4_plan()
    for spec in plan["runs"]:
        if spec["task_id"] == "py-e4-delta":
            spec["task_id"] = "py-e1-alpha"
    moved = {"artifacts/studies/e4/plan.json": json.dumps(plan)}
    ctx = project(git_repo, commit, rows=retask("py-e1-alpha"), extra=moved)
    with pytest.raises(GateError, match="overlap E1"):
        ship_check.g9(ctx)


def test_a_pilot_task_is_not_held_out(git_repo: Path, commit: Commit) -> None:
    plan = e4_plan()
    for spec in plan["runs"]:
        if spec["task_id"] == "py-e4-delta":
            spec["task_id"] = "pilot-csv-stats"
    plan["notes"] = json.dumps({"e4_tasks": ["py-e4-gamma", "pilot-csv-stats"]})
    pilot = {
        "artifacts/studies/e4/plan.json": json.dumps(plan),
        "bench/tasks/pilot-csv-stats/task.toml": 'id = "pilot-csv-stats"\n',
    }
    ctx = project(git_repo, commit, rows=retask("pilot-csv-stats"), extra=pilot)
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
        pytest.param({"seed": 7}, id="seed"),
    ],
)
def test_e4_rows_must_agree_with_their_banked_runs(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    def edit(records: list[dict[str, Any]]) -> None:
        records[1].update(change)

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


def test_a_frozen_e4_preregistration_needs_confirmatory_results(
    git_repo: Path, commit: Commit
) -> None:
    text = "# E4 (SYNTHETIC test preregistration)\n"
    digest = hashlib.sha256(text.encode()).hexdigest()
    entry = {
        "file": "prereg/0002-e4-mitigation.md",
        "sha256": digest,
        "prev": "0" * 64,
        "entry_hash": "0" * 64,
        "frozen_at": "2026-11-04",
    }
    extra = {
        "prereg/0002-e4-mitigation.md": text,
        "prereg/LOCK.json": json.dumps({"entries": [entry]}),
    }
    ctx = project(git_repo, commit, extra=extra)
    with pytest.raises(GateError, match="not marked confirmatory"):
        ship_check.g9(ctx)


# ---------------------------------------------------------------- review-1 (old code: PASS)


def e4_results_of(ctx: ship_check.Context) -> dict[str, Any]:
    """The committed SYNTHETIC artifacts/e4/results.json."""
    data = json.loads((ctx.clone / "artifacts/e4/results.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_e4_fixture_passes_the_e4_checks(git_repo: Path, commit: Commit) -> None:
    ctx = project(git_repo, commit)
    assert ship_check.check_e4(ctx.clone, e4_results_of(ctx)) == (2, 32)


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
        assert recs[2]["config_id"] == "ma-qwen7b"
        recs[2]["model"] = model_of("ma-granite8b")

    def starts(body: dict[str, Any]) -> None:
        if body["run_id"] == "e4-002-ma-qwen7b-none":
            body["model"] = model_of("ma-granite8b")

    with pytest.raises(GateError, match="not by its planned agent"):
        ship_check.g9(project(git_repo, commit, records=records, starts=starts))


def test_an_e4_plan_arm_without_its_agent_fails(git_repo: Path, commit: Commit) -> None:
    plan = e4_plan()
    del plan["arms"][1]["model"]
    ctx = project(git_repo, commit, extra={"artifacts/studies/e4/plan.json": json.dumps(plan)})
    with pytest.raises(GateError, match="arm without a config_id, driver, or model"):
        ship_check.g9(ctx)


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


def test_a_control_and_one_mitigation_are_a_comparison(git_repo: Path, commit: Commit) -> None:
    ctx = project(git_repo, commit, mitigations=("none", "hook"))
    assert ship_check.check_e4(ctx.clone, e4_results_of(ctx)) == (2, 16)


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
