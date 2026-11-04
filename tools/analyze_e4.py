"""Analyze the banked E4 runs as preregistered and write ``artifacts/e4/results.json``.

    python tools/analyze_e4.py                 # exploratory until prereg 0002 is frozen
    python tools/analyze_e4.py --confirmatory  # refused unless every rule below holds

Reads every ``artifacts/studies/e4/runs/<run_id>/run.json`` with its ``ledger.jsonl``
(the ledger's hash chain and its ``run_start`` and ``run_end`` events must agree with
the record), the E4 plan ``artifacts/studies/e4/plan.json`` (every banked run must be a
planned run with the planned task, configuration, conditions, seed, and mitigation;
planned runs that are not banked are counted as a shortfall), the held-out seeded
evaluation ``artifacts/e0/seeded_eval.json`` (the claim types that met the G5 thresholds,
the only ones Z1 counts), and E1's task ids from ``artifacts/e1/runs.jsonl`` and
``artifacts/studies/e1/plan.json`` (the E4 tasks must be disjoint from them). The
analysis itself is :mod:`receipts.study.results_e4`, which implements
``prereg/0002-e4-mitigation.md`` sections 4 and 5.

Provenance records the git SHA of this repository, the command, the time, the SHA-256 of
every input file, the preregistration's path and SHA-256, the SHA-256 of the analysis
code, and any tracked files with uncommitted changes. ``--confirmatory`` is refused
unless the preregistration is frozen in ``prereg/LOCK.json``, the plan was read, every
run is a real, non-synthetic run, the settings are the preregistered ones, and the
tasks are shown to be held out: E1's task ids (from its plan or its rows) and the split
the E1 plan records must both be read and non-empty. ``--n-boot``, ``--seed``, and
``--n-agq`` exist only for quick exploratory checks, which never write the default
``artifacts/e4/results.json`` (pass ``--out`` with another path), and no exploratory run
replaces a confirmatory artifact; both are refused before any analysis
(:func:`output_problem`). Exit status: 0 written, 1 refused or invalid input (the
reason goes to stderr).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from receipts.study import results_e4

ROOT = Path(__file__).resolve().parents[1]
RUNS = "artifacts/studies/e4/runs"
PLAN = "artifacts/studies/e4/plan.json"
SEEDED_EVAL = "artifacts/e0/seeded_eval.json"
E1_ROWS = "artifacts/e1/runs.jsonl"
E1_PLAN = "artifacts/studies/e1/plan.json"
OUT = "artifacts/e4/results.json"
ANALYSIS_CODE = ("src/receipts/study/results_e4.py", "tools/analyze_e4.py")


def _git(*args: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )
    return proc.stdout if proc.returncode == 0 else None


def git_sha() -> str:
    """HEAD of this repository ("unknown" outside a git checkout)."""
    out = _git("rev-parse", "HEAD")
    return out.strip() if out else "unknown"


def uncommitted() -> list[str]:
    """Tracked files of this repository with uncommitted changes."""
    out = _git("status", "--porcelain", "--untracked-files=no") or ""
    return sorted(line[3:] for line in out.splitlines() if line.strip())


def e1_task_ids(root: Path) -> tuple[list[str] | None, list[str]]:
    """Every task id E1 used, from its rows and its plan, and the files read.

    Returns ``(None, [])`` when neither file exists (E1 has not been planned here).
    """
    tasks: set[str] = set()
    sources: list[str] = []
    plan = root / E1_PLAN
    if plan.is_file():
        data = json.loads(plan.read_text(encoding="utf-8"))
        tasks.update(str(r["task_id"]) for r in data.get("runs", []))
        try:
            notes = json.loads(str(data.get("notes", "")))
        except json.JSONDecodeError:
            notes = {}
        if isinstance(notes, dict):
            tasks.update(str(t) for t in notes.get("e1_tasks", []))
        sources.append(E1_PLAN)
    rows = root / E1_ROWS
    if rows.is_file():
        for line in rows.read_text(encoding="utf-8").splitlines():
            if line.strip():
                tasks.add(str(json.loads(line)["task_id"]))
        sources.append(E1_ROWS)
    return (sorted(tasks) if sources else None), sources


def split_e4_tasks(root: Path) -> list[str] | None:
    """The E4 side of the task split recorded in the E1 plan's notes, or None."""
    plan = root / E1_PLAN
    if not plan.is_file():
        return None
    try:
        notes = json.loads(str(json.loads(plan.read_text(encoding="utf-8")).get("notes", "")))
    except json.JSONDecodeError:
        return None
    listed = notes.get("e4_tasks") if isinstance(notes, dict) else None
    return sorted(str(t) for t in listed) if isinstance(listed, list) else None


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _settings(args: argparse.Namespace) -> results_e4.AnalysisSettings:
    default = results_e4.AnalysisSettings()
    return results_e4.AnalysisSettings(
        n_agq=default.n_agq if args.n_agq is None else args.n_agq,
        n_boot=default.n_boot if args.n_boot is None else args.n_boot,
        seed=default.seed if args.seed is None else args.seed,
    )


def output_path(args: argparse.Namespace) -> Path:
    """``--out``, or the default artifact path under ``--root``."""
    out: Path = args.out if args.out is not None else args.root / OUT
    return out


def output_problem(
    root: Path,
    out: Path,
    *,
    confirmatory: bool = False,
    settings: results_e4.AnalysisSettings | None = None,
) -> str | None:
    """Why this run may not write ``out`` (None when it may); checked before any analysis.

    ``<root>/artifacts/e4/results.json`` holds the full analysis, so a quick check (any
    setting other than the preregistered value) never writes it. No run replaces a
    confirmatory artifact with an exploratory one, at that path or any other
    (:func:`receipts.study.results_e4.holds_confirmatory_artifact`). Either run can
    write to ``--out`` with another path.
    """
    changed = (settings or results_e4.AnalysisSettings()).differences()
    if changed and out.resolve() == (root / OUT).resolve():
        return (
            f"a quick check never writes {OUT}, which holds the full analysis; pass --out "
            f"with another path. Settings that differ: {'; '.join(changed)}"
        )
    if not confirmatory and results_e4.holds_confirmatory_artifact(out):
        return (
            f"{_rel(out, root)} holds a confirmatory artifact and an exploratory run never "
            "replaces it; rerun with --confirmatory, or pass --out with another path"
        )
    return None


def build(args: argparse.Namespace, argv: Sequence[str]) -> tuple[dict[str, Any], Path]:
    """Read every input, run the analysis, and return the artifact and its output path."""
    root: Path = args.root
    banked = results_e4.load_e4_runs(root / RUNS)
    records = [b.record for b in banked]
    inputs: dict[str, str] = {}
    for run in banked:
        inputs[_rel(run.path, root)] = run.sha256
        inputs[_rel(run.ledger_path, root)] = run.ledger_sha256
    seeded = root / SEEDED_EVAL
    if not seeded.is_file():
        raise ValueError(f"{SEEDED_EVAL} is missing: Z1 counts only claim types that met G5")
    valid = results_e4.g5_valid_types(json.loads(seeded.read_text(encoding="utf-8")))
    inputs[SEEDED_EVAL] = results_e4.sha256_file(seeded)
    prereg_file = root / args.prereg
    prereg_text = prereg_file.read_text(encoding="utf-8") if prereg_file.is_file() else ""
    plan_path = root / PLAN
    plan = None
    if plan_path.is_file():
        inputs[PLAN] = results_e4.sha256_file(plan_path)
        plan = results_e4.check_against_plan(
            records,
            json.loads(plan_path.read_text(encoding="utf-8")),
            sha256=inputs[PLAN],
            recorded_sha256=results_e4.recorded_plan_sha256(prereg_text),
        )
    e1_tasks, e1_sources = e1_task_ids(root)
    for rel in e1_sources:
        inputs[rel] = results_e4.sha256_file(root / rel)
    status = results_e4.prereg_status(root, args.prereg)
    if status.sha256:
        inputs[args.prereg] = status.sha256
    provenance = {
        "git_sha": git_sha(),
        "command": " ".join(["python", "tools/analyze_e4.py", *argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": dict(sorted(inputs.items())),
        "analysis_code": {rel: results_e4.sha256_file(ROOT / rel) for rel in ANALYSIS_CODE},
        "uncommitted_at_analysis": uncommitted(),
        "run_git_shas": sorted({str(r.get("provenance", {}).get("git_sha")) for r in records}),
    }
    artifact = results_e4.build_results(
        records,
        valid_types=valid,
        prereg=status,
        plan=plan,
        e1_tasks=e1_tasks,
        split_tasks=split_e4_tasks(root),
        provenance=provenance,
        settings=_settings(args),
        confirmatory=args.confirmatory,
    )
    return artifact, output_path(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the E4 results artifact; 1 with the reason on stderr when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to read")
    parser.add_argument("--prereg", default=results_e4.PREREG_PATH)
    parser.add_argument("--out", type=Path, default=None, help=f"default: <root>/{OUT}")
    parser.add_argument("--confirmatory", action="store_true")
    parser.add_argument("--n-boot", type=int, default=None, help="exploratory checks only")
    parser.add_argument("--seed", type=int, default=None, help="exploratory checks only")
    parser.add_argument("--n-agq", type=int, default=None, help="exploratory checks only")
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    problem = output_problem(
        args.root, output_path(args), confirmatory=args.confirmatory, settings=_settings(args)
    )
    if problem is not None:
        print(f"E4: {problem}", file=sys.stderr)
        return 1
    try:
        artifact, out = build(args, arguments)
    except ValueError as exc:  # includes ConfirmatoryRefusedError
        print(f"E4: {exc}", file=sys.stderr)
        return 1
    results_e4.write_strict_json(out, artifact)
    kind = "confirmatory" if artifact["confirmatory"] else "exploratory"
    label = " SYNTHETIC" if artifact["synthetic"] else ""
    print(
        f"E4: wrote {out} ({kind}{label}): {artifact['runs']['banked']} runs on "
        f"{len(artifact['tasks'])} held-out tasks"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
