"""Run the preregistered E1 and E2 analysis (prereg/0001-e1-main-study.md, section 5).

    python tools/analyze.py e1   # artifacts/e1/results.json from artifacts/e1/runs.jsonl,
                                 # artifacts/e0/seeded_eval.json, artifacts/studies/e1/plan.json
    python tools/analyze.py e2   # artifacts/e2/mechanism.json from the same rows and the
                                 # banked ledgers under artifacts/studies/e1/runs/

The computation is :mod:`receipts.study.results`. This tool reads the inputs, checks
that the preregistration is frozen (listed in ``prereg/LOCK.json`` with its current
SHA-256, an intact hash chain, and a committed lock entry), that the analysis code is
committed, and whether it changed after the freeze commit (a deviation the
preregistration requires to be reported with both results), and writes the artifact as
strict JSON with provenance: the git SHA, the command, the time, the SHA-256 of every
input file, the preregistration's path and SHA-256, the SHA-256 of every analysis code
file that ran, and the Python and library versions. Both commands check the rows
against the study plan and the preregistration's ``planned_runs_per_config:`` and
``plan_sha256:`` lines (:func:`receipts.study.results.run_checks`; a missing line is a
blocker), so a problem that keeps E1 from being confirmatory keeps E2 from it too.

Every path is relative to ``--root`` (default: this repository), and so are the git
checks. ``--n-boot`` exists for tests: any value other than the preregistered 2000 makes
the artifact non-confirmatory. A synthetic artifact is never written to this
repository's gate paths (``artifacts/e1/results.json``, ``artifacts/e2/mechanism.json``).
Errors (a missing or malformed input) print one line and exit with status 2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import prereg
import receipts.analysis
import receipts.evaluation.mechanism
import receipts.ledger.events
import receipts.study.aggregate
import receipts.study.spec
from gitutil import GitError, git, sha256_file
from receipts.study import results

ROOT = Path(__file__).resolve().parents[1]
RUNS = "artifacts/e1/runs.jsonl"
SEEDED = "artifacts/e0/seeded_eval.json"
PLAN = "artifacts/studies/e1/plan.json"
RUN_DIRS = "artifacts/studies/e1/runs"
E1_OUT = "artifacts/e1/results.json"
E2_OUT = "artifacts/e2/mechanism.json"
#: The analysis code, checked for uncommitted changes and for changes after the freeze.
ANALYSIS_CODE = (
    "tools/analyze.py",
    "src/receipts/study/results.py",
    "src/receipts/study/aggregate.py",
    "src/receipts/study/spec.py",
    "src/receipts/analysis",
    "src/receipts/evaluation/mechanism.py",
    "src/receipts/ledger/events.py",
)


# Inputs ---------------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object; raises OSError or ValueError."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows (blank lines skipped); each must be a JSON object."""
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {number} is not valid JSON ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {number} is not a JSON object")
        rows.append(row)
    return rows


def freeze_commit(root: Path, rel: str) -> str | None:
    """The first commit whose ``prereg/LOCK.json`` lists ``rel``, or None."""
    try:
        shas = git(root, "log", "--format=%H", "--reverse", "--", prereg.LOCK).split()
    except GitError:
        return None
    for sha in shas:
        try:
            data = json.loads(git(root, "show", f"{sha}:{prereg.LOCK}"))
        except (GitError, json.JSONDecodeError):
            continue
        entries = data.get("entries", []) if isinstance(data, dict) else []
        if any(isinstance(e, dict) and e.get("file") == rel for e in entries):
            return sha
    return None


def prereg_status(root: Path, rel: str) -> results.PreregInfo:
    """Whether ``rel`` is frozen: in an intact, committed lock chain with its current hash.

    Raises:
        OSError: The preregistration file cannot be read.
    """
    path = root / rel
    text = path.read_text(encoding="utf-8")
    digest = sha256_file(path)
    planned, plan_digest = results.parse_prereg_fields(text)
    problems: list[str] = []
    try:
        entries = prereg.load_lock(root)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        entries = []
        problems.append(f"{prereg.LOCK} is unreadable: {exc}")
    previous = prereg.GENESIS
    for entry in entries:
        expected = prereg.entry_hash(previous, entry.file, entry.sha256)
        if entry.prev != previous or entry.entry_hash != expected:
            problems.append(f"the {prereg.LOCK} hash chain is broken at {entry.file}")
        previous = entry.entry_hash
    mine = [e for e in entries if e.file == rel]
    if not mine:
        problems.append(f"{rel} is not in {prereg.LOCK}")
    elif mine[0].sha256 != digest:
        problems.append(
            f"{rel} changed after it was frozen (locked {mine[0].sha256[:12]}, now {digest[:12]})"
        )
    elif freeze_commit(root, rel) is None:
        problems.append(f"the {prereg.LOCK} entry for {rel} is not committed, so it is not frozen")
    return results.PreregInfo(
        path=rel,
        sha256=digest,
        frozen=not problems,
        problems=tuple(problems),
        planned_runs_per_config=planned,
        plan_sha256=plan_digest,
    )


def load_plan(root: Path, rel: str) -> results.StudyPlan | None:
    """The study plan at ``rel``, or None when there is no such file."""
    path = root / rel
    if not path.is_file():
        return None
    return results.study_plan(read_json(path), path=rel, sha256=sha256_file(path))


def load_e1_inputs(
    root: Path, runs: str, seeded: str, plan: str, prereg_rel: str
) -> tuple[list[dict[str, Any]], dict[str, Any], results.PreregInfo, results.StudyPlan | None]:
    """The rows, the G5 evaluation, the preregistration status, and the plan (or None)."""
    rows = read_jsonl(root / runs)
    evaluation = read_json(root / seeded)
    info = prereg_status(root, prereg_rel)
    return rows, evaluation, info, load_plan(root, plan)


# Code state and provenance ----------------------------------------------------------------


def head_sha(root: Path) -> str | None:
    """HEAD of the repository at ``root``, or None outside a repository."""
    try:
        return git(root, "rev-parse", "HEAD").strip()
    except GitError:
        return None


def uncommitted(root: Path, paths: Sequence[str]) -> list[str] | None:
    """Paths under ``paths`` with uncommitted or untracked changes; None outside a repository."""
    try:
        out = git(root, "status", "--porcelain", "--untracked-files=all", "--", *paths)
    except GitError:
        return None
    return sorted(line[3:] for line in out.splitlines() if line.strip())


def changed_since(root: Path, commit: str, paths: Sequence[str]) -> list[str]:
    """Paths under ``paths`` that differ between ``commit`` and HEAD."""
    out = git(root, "diff", "--name-only", commit, "HEAD", "--", *paths)
    return sorted(p for p in out.splitlines() if p)


def code_checks(
    root: Path, info: results.PreregInfo
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Confirmatory blockers and deviations from the state of the analysis code.

    Returns:
        ``(blockers, deviations, dirty)``: uncommitted analysis code (or no repository)
        blocks a confirmatory artifact, because it could not be reproduced from its git
        SHA; analysis code committed after the freeze commit is a deviation (section 5).
    """
    blockers: list[str] = []
    deviations: list[dict[str, Any]] = []
    dirty = uncommitted(root, ANALYSIS_CODE)
    if dirty is None:
        blockers.append(f"{root} is not a git repository, so the analysis code has no commit")
        return blockers, deviations, []
    if dirty:
        blockers.append(
            "the analysis code has uncommitted changes, so the artifact could not be "
            "reproduced from its git SHA: " + ", ".join(dirty)
        )
    frozen_at = freeze_commit(root, info.path) if info.frozen else None
    if frozen_at is not None:
        changed = changed_since(root, frozen_at, ANALYSIS_CODE)
        if changed:
            deviations.append(
                {
                    "kind": "analysis_code_changed",
                    "prereg_section": "5",
                    "detail": f"analysis code changed after the freeze commit {frozen_at[:12]}: "
                    + ", ".join(changed)
                    + "; report the results of the code at the freeze commit beside these",
                }
            )
    return blockers, deviations, dirty


def display_path(path: Path) -> str:
    """``path`` relative to this repository when inside it, else absolute (POSIX)."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def code_hashes() -> dict[str, str]:
    """SHA-256 of every analysis code file that this process imported, by path."""
    modules = (
        results,
        receipts.study.aggregate,
        receipts.study.spec,
        receipts.evaluation.mechanism,
        receipts.ledger.events,
    )
    files = [Path(__file__), *(Path(str(m.__file__)) for m in modules)]
    files += sorted(Path(str(receipts.analysis.__file__)).parent.glob("*.py"))
    return {display_path(p): sha256_file(p) for p in files}


def input_hashes(root: Path, rels: Sequence[str]) -> dict[str, str]:
    """SHA-256 of each input file that exists, by its path relative to ``root``."""
    return {rel: sha256_file(root / rel) for rel in rels if (root / rel).is_file()}


def provenance(
    root: Path,
    argv: Sequence[str],
    inputs: Mapping[str, str],
    info: results.PreregInfo,
    dirty: Sequence[str],
) -> dict[str, Any]:
    """Provenance of an artifact written by this tool."""
    return {
        "git_sha": head_sha(root) or "unknown: not a git repository",
        "command": " ".join(["python", "tools/analyze.py", *argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": dict(inputs),
        "prereg": info.path,
        "prereg_sha256": info.sha256,
        "analysis_code": code_hashes(),
        "uncommitted_analysis_code": list(dirty),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": version("numpy"),
            "scipy": version("scipy"),
        },
    }


# Commands -------------------------------------------------------------------------------


def _refuse_gate_path(out: Path, synthetic: bool) -> None:
    gates = {(ROOT / E1_OUT).resolve(), (ROOT / E2_OUT).resolve()}
    if synthetic and out.resolve() in gates:
        raise ValueError(f"refusing to write a synthetic artifact to the gate path {out}")


def write_artifact(path: Path, artifact: Mapping[str, Any]) -> None:
    """Write strict JSON (sorted keys, NaN refused) with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")


def _report(name: str, artifact: Mapping[str, Any], summary: str, out: str) -> None:
    print(
        f"{name}: {summary}; synthetic={artifact['synthetic']}; "
        f"confirmatory={artifact['confirmatory']}; wrote {out}"
    )
    for reason in artifact["confirmatory_blockers"]:
        print(f"  not confirmatory: {reason}")


def run_e1(root: Path, args: argparse.Namespace, argv: Sequence[str]) -> int:
    """``e1``: write ``artifacts/e1/results.json``."""
    rows, evaluation, info, plan = load_e1_inputs(
        root, args.runs, args.seeded, args.plan, args.prereg
    )
    out = root / args.out
    _refuse_gate_path(out, results.synthetic_flag(rows))
    blockers, deviations, dirty = code_checks(root, info)
    inputs = input_hashes(root, [args.runs, args.seeded, args.plan, args.prereg, prereg.LOCK])
    artifact = results.e1_results(
        rows,
        evaluation,
        prereg=info,
        plan=plan,
        provenance=provenance(root, argv, inputs, info, dirty),
        settings=results.E1Settings(n_boot=args.n_boot),
        blockers=blockers,
        deviations=deviations,
    )
    write_artifact(out, artifact)
    _report("e1", artifact, f"{len(artifact['configs'])} configuration(s)", args.out)
    return 0


def run_e2(root: Path, args: argparse.Namespace, argv: Sequence[str]) -> int:
    """``e2``: write ``artifacts/e2/mechanism.json``."""
    rows = read_jsonl(root / args.runs)
    out = root / args.out
    _refuse_gate_path(out, results.synthetic_flag(rows))
    info = prereg_status(root, args.prereg)
    blockers, deviations, dirty = code_checks(root, info)
    # e2_mechanism checks the rows against this plan as e1_results does (run_checks).
    plan = load_plan(root, args.plan)
    inputs = input_hashes(root, [args.runs, args.plan, args.prereg, prereg.LOCK])
    runs_dir = root / args.run_dirs

    def load(run_id: str) -> results.RunEvidence:
        return results.load_run_evidence(runs_dir / run_id, root=root)

    artifact = results.e2_mechanism(
        rows,
        load,
        prereg=info,
        plan=plan,
        provenance=provenance(root, argv, inputs, info, dirty),
        blockers=blockers,
        deviations=deviations,
    )
    write_artifact(out, artifact)
    _report("e2", artifact, f"{artifact['n_contradicted']} contradicted claim(s)", args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=ROOT, help="repository root (default: here)")
    common.add_argument("--runs", default=RUNS, help=f"E1 rows (default {RUNS})")
    common.add_argument("--prereg", default=results.PREREG_E1, help="the preregistration")
    common.add_argument("--plan", default=PLAN, help=f"study plan (default {PLAN})")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e1 = sub.add_parser("e1", parents=[common], help="E1 results (RQ1, RQ2)")
    e1.add_argument("--seeded", default=SEEDED, help=f"held-out G5 evaluation (default {SEEDED})")
    e1.add_argument("--out", default=E1_OUT, help=f"output (default {E1_OUT})")
    e1.add_argument(
        "--n-boot",
        type=int,
        default=results.E1Settings().n_boot,
        help="bootstrap resamples (tests only: any other value is not confirmatory)",
    )
    e2 = sub.add_parser("e2", parents=[common], help="E2 mechanism mix (RQ3)")
    e2.add_argument("--run-dirs", default=RUN_DIRS, help=f"banked runs (default {RUN_DIRS})")
    e2.add_argument("--out", default=E2_OUT, help=f"output (default {E2_OUT})")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``e1`` or ``e2``; returns 0, or 2 after printing an input error."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(args_list)
    root = Path(args.root).resolve()
    try:
        if args.command == "e1":
            return run_e1(root, args, args_list)
        return run_e2(root, args, args_list)
    except (OSError, ValueError) as exc:
        print(f"analyze: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
