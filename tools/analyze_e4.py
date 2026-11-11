"""Analyze the banked E4 runs as preregistered and write ``artifacts/e4/results.json``.

    python tools/analyze_e4.py                 # exploratory until prereg 0002 is frozen
    python tools/analyze_e4.py --confirmatory  # refused unless every rule below holds

Inputs, every path under ``--root`` (default: this repository):

- ``artifacts/e4/runs.jsonl``: the rows ``python tools/bank_study.py e4`` writes, whose
  claims and verdicts come from the re-verification at banking (DECISIONS D42 item 1),
  and its banking provenance ``artifacts/e4/runs.provenance.json``, whose
  ``rows_sha256`` must be the SHA-256 of the rows file (otherwise the rows were changed
  after banking and the analysis stops);
- the banked runs ``artifacts/studies/e4/runs/<run_id>/`` (``run.json`` and
  ``ledger.jsonl``, hash chain checked): the rows must be the rows of exactly these
  runs, and their records show whether each run is real;
- the held-out seeded evaluation ``artifacts/e0/seeded_eval.json``: the valid claim types
  and the evaluated instrument (:func:`receipts.study.rescore.load_valid_types`);
- the E4 plan ``artifacts/studies/e4/plan.json``, the E1 plan
  ``artifacts/studies/e1/plan.json`` (the held-out split, E1's tasks, and the arms E4
  must share), and ``artifacts/e1/runs.jsonl`` (E1's tasks);
- the banked failure log ``artifacts/studies/e4/failures.jsonl``, when there is one;
- the preregistration, ``prereg/LOCK.json``, and git: the freeze commit (the first commit
  whose ``prereg/LOCK.json`` lists the preregistration), the commit state of the
  analysis code (:data:`ANALYSIS_CODE`), for each run's commit whether it is the freeze
  commit or a later one and its git trees of the evaluated instrument paths, and each
  task's tree hash at the freeze commit (:func:`task_tree_at`).

The analysis itself is :mod:`receipts.study.results_e4`, which implements
``prereg/0002-e4-mitigation.md``. Provenance records the git SHA, the command, the time,
the SHA-256 of every input file, the preregistration's path and SHA-256, the freeze
commit, the SHA-256 of every analysis code file that ran, and the analysis code's
uncommitted files. Every artifact lists its ``confirmatory_blockers``; ``--confirmatory``
is refused unless there are none (prereg 0002 section 7). Analysis code changed after
the freeze commit is the deviation ``analysis_code_changed``; running the code of the
freeze commit on the same inputs, which the preregistration also asks for, is left to
the operator. ``--n-boot``, ``--seed``, and ``--n-agq`` exist only for quick exploratory
checks, which never write the default ``artifacts/e4/results.json`` (pass ``--out`` with
another path), and no exploratory run replaces a confirmatory artifact; both are
refused before any analysis (:func:`output_problem`). Exit status: 0 written, 1 refused
or invalid input (the reason goes to stderr).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import receipts
import receipts.analysis
from receipts.bench import hashing
from receipts.client import models
from receipts.ledger import events
from receipts.study import rescore, results_e4, spec

ROOT = Path(__file__).resolve().parents[1]
RUNS = "artifacts/studies/e4/runs"
ROWS = "artifacts/e4/runs.jsonl"
ROWS_PROVENANCE = "artifacts/e4/runs.provenance.json"
PLAN = "artifacts/studies/e4/plan.json"
FAILURES = "artifacts/studies/e4/failures.jsonl"
SEEDED_EVAL = "artifacts/e0/seeded_eval.json"
E1_ROWS = "artifacts/e1/runs.jsonl"
E1_PLAN = "artifacts/studies/e1/plan.json"
LOCK = "prereg/LOCK.json"
OUT = "artifacts/e4/results.json"
#: The analysis code (prereg 0002 section 7): this tool, ``receipts.study.results_e4``,
#: ``receipts.analysis``, and ``receipts.study.rescore`` (the valid types), with the
#: modules they read the design, the ledgers, the pinned models, and task trees from.
#: Its uncommitted changes block a confirmatory artifact, and its changes after the
#: freeze commit are the deviation ``analysis_code_changed``.
ANALYSIS_CODE: tuple[str, ...] = (
    "tools/analyze_e4.py",
    "src/receipts/study/results_e4.py",
    "src/receipts/study/rescore.py",
    "src/receipts/analysis",
    "src/receipts/study/spec.py",
    "src/receipts/ledger/events.py",
    "src/receipts/client/models.py",
    "src/receipts/bench/hashing.py",
)
_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# Git -------------------------------------------------------------------------------------


def _run_git(root: Path, *args: str, stdin: bytes | None = None) -> bytes | None:
    """``git -C root <args>`` stdout as bytes, or None when git fails."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args], input=stdin, capture_output=True, check=False
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git(root: Path, *args: str) -> str | None:
    out = _run_git(root, *args)
    return None if out is None else out.decode("utf-8", "replace")


def is_checkout(root: Path) -> bool:
    """Whether ``root`` is the top-level directory of a git checkout."""
    top = _git(root, "rev-parse", "--show-toplevel")
    return top is not None and Path(top.strip()).resolve() == root.resolve()


def git_sha(root: Path = ROOT) -> str:
    """HEAD of the checkout at ``root`` ("unknown" outside a git checkout)."""
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out else "unknown"


def uncommitted(root: Path, paths: Sequence[str]) -> list[str] | None:
    """Files under ``paths`` with uncommitted changes, untracked ones included.

    None when ``root`` is not the top of a git checkout.
    """
    if not is_checkout(root):
        return None
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    if out is None:
        return None
    tokens, found, index = out.split("\0"), set(), 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        found.add(token[3:])
        if token[0] in "RC" and index < len(tokens):
            found.add(tokens[index])
            index += 1
    return sorted(found)


def changed_since(root: Path, commit: str, paths: Sequence[str]) -> list[str] | None:
    """Files under ``paths`` that differ between ``commit`` and HEAD (None: git failed)."""
    out = _git(root, "diff", "--name-only", "-z", commit, "HEAD", "--", *paths)
    return None if out is None else sorted(p for p in out.split("\0") if p)


def lock_commit(root: Path, rel: str) -> results_e4.LockCommit | None:
    """The first commit whose ``prereg/LOCK.json`` lists ``rel``, with the SHA-256 it records.

    None when no commit does, or ``root`` is not a git checkout.
    """
    if not is_checkout(root):
        return None
    out = _git(root, "log", "--format=%H", "--reverse", "--topo-order", "--", LOCK)
    for sha in (out or "").split():
        text = _git(root, "show", f"{sha}:{LOCK}")
        try:
            data = json.loads(text) if text is not None else None
        except json.JSONDecodeError:
            continue
        entries = data.get("entries") if isinstance(data, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("file") == rel:
                return results_e4.LockCommit(sha, str(entry.get("sha256")))
    return None


def tree_at(root: Path, commit: str, rel: str) -> str | None:
    """The git object id of ``commit:rel`` (a tree for a directory), or None."""
    out = _git(root, "rev-parse", "--verify", "-q", f"{commit}:{rel}")
    return out.strip() if out else None


def is_ancestor(root: Path, older: str, newer: str) -> bool | None:
    """Whether ``older`` is ``newer`` or one of its ancestors (None when git cannot say)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return {0: True, 1: False}.get(proc.returncode)


def commit_facts(
    root: Path, commit: str, freeze: str | None, paths: Sequence[str]
) -> results_e4.CommitFacts:
    """What git says about a run's commit: known, after the freeze, and its instrument trees.

    A value that is not a hex commit id is never passed to git and counts as unknown.
    """
    known = bool(_SHA.match(commit)) and is_checkout(root)
    if known:
        known = _run_git(root, "cat-file", "-e", f"{commit}^{{commit}}") is not None
    if not known:
        return results_e4.CommitFacts(False, None, None)
    after = None if freeze is None else is_ancestor(root, freeze, commit)
    trees = {path: tree_at(root, commit, path) for path in paths}
    return results_e4.CommitFacts(True, after, trees)


def _blobs(root: Path, ids: Sequence[str]) -> list[bytes] | None:
    """The contents of the blobs ``ids`` (``git cat-file --batch``), or None."""
    out = _run_git(root, "cat-file", "--batch", stdin="".join(f"{i}\n" for i in ids).encode())
    if out is None:
        return None
    blobs: list[bytes] = []
    position = 0
    for _ in ids:
        end = out.find(b"\n", position)
        header = out[position:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
            return None
        start = end + 1
        size = int(header[2])
        blobs.append(out[start : start + size])
        position = start + size + 1
    return blobs


def task_tree_at(root: Path, commit: str, task_id: str) -> str | None:
    """The hash of ``bench/tasks/<task_id>/`` as committed in ``commit``, or None.

    The committed files are written to a temporary directory and hashed with
    :func:`receipts.bench.hashing.tree_sha256`, the function ``tools/run_study.py`` records
    ``task_tree_sha256`` with, so the two values compare one to one. None when the task
    is not in the commit, its id is not one safe directory name, or git fails.
    """
    if not _TASK_ID.match(task_id) or ".." in task_id:
        return None
    rel = f"bench/tasks/{task_id}"
    listing = _run_git(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", rel)
    if listing is None:
        return None
    files: list[tuple[str, str]] = []
    for item in listing.split(b"\0"):
        meta, _, raw = item.partition(b"\t")
        parts = meta.split(b" ")
        if len(parts) == 3 and parts[1] == b"blob":
            files.append((parts[2].decode(), raw.decode("utf-8", "surrogateescape")))
    contents = _blobs(root, [oid for oid, _ in files]) if files else None
    if contents is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "task"
        for (_, name), content in zip(files, contents, strict=True):
            target = base / Path(name).relative_to(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return hashing.tree_sha256(base)


def run_code_facts(
    root: Path, freeze: str | None, rows: Sequence[Mapping[str, Any]]
) -> results_e4.RunCodeFacts:
    """The git facts the run checks need, for the commits and tasks of ``rows``.

    A run commit's instrument trees are read for the paths a row binds
    (:data:`receipts.study.rescore.INSTRUMENT_RECORD_PATHS`, DECISIONS D47), the ones
    :func:`receipts.study.results_e4.run_checks` compares with the evaluated trees.
    """
    shas: set[str] = set()
    for row in rows:
        code = row.get("run_code")
        sha = code.get("git_sha") if isinstance(code, Mapping) else None
        if isinstance(sha, str) and sha:
            shas.add(sha)
    paths = list(rescore.INSTRUMENT_RECORD_PATHS)
    commits = {sha: commit_facts(root, sha, freeze, paths) for sha in sorted(shas)}
    tasks = sorted({str(r.get("task_id")) for r in rows})
    trees = {} if freeze is None else {t: task_tree_at(root, freeze, t) for t in tasks}
    return results_e4.RunCodeFacts(freeze, commits, trees)


# The analysis code ----------------------------------------------------------------------


def code_files() -> dict[str, Path]:
    """Every analysis code file this process runs, by its path in the repository."""
    src = Path(receipts.__file__).resolve().parents[1]
    files: dict[str, Path] = {"tools/analyze_e4.py": Path(__file__).resolve()}
    modules = (results_e4, rescore, spec, events, models, hashing)
    paths = [Path(str(m.__file__)).resolve() for m in modules]
    paths += sorted(Path(str(receipts.analysis.__file__)).resolve().parent.glob("*.py"))
    for path in paths:
        try:
            files["src/" + path.relative_to(src).as_posix()] = path
        except ValueError:
            files[path.as_posix()] = path
    return files


def analysis_code_state(
    root: Path, freeze: str | None
) -> tuple[list[str], list[dict[str, Any]], dict[str, str], list[str]]:
    """Problems and deviations of the analysis code, its file hashes, and its dirty files.

    Problems (they block a confirmatory artifact): ``root`` is not a git checkout; the
    code that runs differs from the files under ``root`` (so the checks below would not
    describe it); or :data:`ANALYSIS_CODE` has uncommitted changes. A change after the
    freeze commit is the deviation ``analysis_code_changed`` (prereg 0002 section 7).

    Returns:
        ``(problems, deviations, hashes, dirty)``.
    """
    files = code_files()
    hashes = {rel: results_e4.sha256_file(path) for rel, path in files.items()}
    problems: list[str] = []
    differ = sorted(
        rel
        for rel, digest in hashes.items()
        if not (root / rel).is_file() or results_e4.sha256_file(root / rel) != digest
    )
    if differ:
        problems.append(
            "the analysis code that runs differs from the files under --root: "
            + ", ".join(differ[:5])
        )
    dirty = uncommitted(root, ANALYSIS_CODE)
    if dirty is None:
        problems.append(f"{root} is not a git checkout, so the analysis code has no commit")
    elif dirty:
        problems.append(
            "the analysis code has uncommitted changes, so the artifact could not be "
            "reproduced from its git SHA: " + ", ".join(dirty[:5])
        )
    deviations: list[dict[str, Any]] = []
    if freeze is not None and dirty is not None:
        changed = changed_since(root, freeze, ANALYSIS_CODE)
        if changed is None:
            problems.append(f"the analysis code cannot be compared with the freeze commit {freeze}")
        elif changed:
            deviations.append(
                {
                    "kind": "analysis_code_changed",
                    "prereg_section": "7",
                    "detail": f"analysis code changed after the freeze commit {freeze[:12]}: "
                    + ", ".join(changed)
                    + "; the result of the freeze-commit code on the same inputs is the "
                    "preregistered one and is reported beside this one",
                    "files": changed,
                }
            )
    return problems, deviations, hashes, dirty or []


# Inputs -----------------------------------------------------------------------------------


def read_json_object(path: Path) -> dict[str, Any]:
    """A JSON object from ``path``; ValueError when it is not one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _notes(plan: Mapping[str, Any]) -> Mapping[str, Any] | None:
    try:
        notes = json.loads(str(plan.get("notes", "")))
    except json.JSONDecodeError:
        return None
    return notes if isinstance(notes, dict) else None


def e1_task_ids(root: Path) -> tuple[list[str] | None, list[str]]:
    """Every task id E1 used, from its rows and its plan, and the files read.

    Returns ``(None, [])`` when neither file exists (E1 has not been planned here).
    """
    tasks: set[str] = set()
    sources: list[str] = []
    plan = root / E1_PLAN
    if plan.is_file():
        data = read_json_object(plan)
        runs = data.get("runs")
        if isinstance(runs, list):
            tasks.update(str(r.get("task_id")) for r in runs if isinstance(r, dict))
        notes = _notes(data)
        listed = notes.get("e1_tasks") if notes is not None else None
        if isinstance(listed, list):
            tasks.update(str(t) for t in listed)
        sources.append(E1_PLAN)
    rows = root / E1_ROWS
    if rows.is_file():
        tasks.update(str(r.get("task_id")) for r in results_e4.load_jsonl_objects(rows))
        sources.append(E1_ROWS)
    return (sorted(tasks) if sources else None), sources


def split_e4_tasks(root: Path) -> list[str] | None:
    """The E4 side of the task split recorded in the E1 plan's notes, or None."""
    plan = root / E1_PLAN
    if not plan.is_file():
        return None
    notes = _notes(read_json_object(plan))
    listed = notes.get("e4_tasks") if notes is not None else None
    return sorted(str(t) for t in listed) if isinstance(listed, list) else None


def e1_arms(root: Path) -> list[Any] | None:
    """The arms of the E1 plan (E4's arms must equal them), or None without an E1 plan."""
    plan = root / E1_PLAN
    if not plan.is_file():
        return None
    arms = read_json_object(plan).get("arms")
    return list(arms) if isinstance(arms, list) else []


def check_banking(root: Path, rows_sha256: str) -> None:
    """Refuse rows that are not the file ``bank_study e4`` wrote.

    Raises:
        ValueError: ``artifacts/e4/runs.provenance.json`` is missing, is not E4's, or
            records another ``rows_sha256``.
    """
    path = root / ROWS_PROVENANCE
    if not path.is_file():
        raise ValueError(
            f"{ROWS_PROVENANCE} is missing: bank the E4 runs with python tools/bank_study.py e4"
        )
    data = read_json_object(path)
    if data.get("study") != "e4" or data.get("rows_sha256") != rows_sha256:
        raise ValueError(
            f"{ROWS} is not the file bank_study wrote ({ROWS_PROVENANCE} records another "
            "study or another rows_sha256); bank the E4 runs again"
        )


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
    """Read every input, run the analysis, and return the artifact and its output path.

    Raises:
        ValueError: An input is missing or malformed, or the analysis refuses it
            (including :class:`receipts.study.results_e4.ConfirmatoryRefusedError`).
        OSError: An input cannot be read.
    """
    root: Path = args.root
    rows_path = root / ROWS
    if not rows_path.is_file():
        raise ValueError(f"{ROWS} is missing: bank the E4 runs with python tools/bank_study.py e4")
    inputs: dict[str, str] = {ROWS: results_e4.sha256_file(rows_path)}
    check_banking(root, inputs[ROWS])
    inputs[ROWS_PROVENANCE] = results_e4.sha256_file(root / ROWS_PROVENANCE)
    rows = results_e4.load_jsonl_objects(rows_path)
    banked = results_e4.load_e4_runs(root / RUNS)
    for run in banked:
        inputs[_rel(run.path, root)] = run.sha256
        inputs[_rel(run.ledger_path, root)] = run.ledger_sha256
    seeded = root / SEEDED_EVAL
    if not seeded.is_file():
        raise ValueError(f"{SEEDED_EVAL} is missing: Z1 counts only the valid claim types")
    valid = rescore.load_valid_types(seeded)
    inputs[SEEDED_EVAL] = str(valid.sha256)
    prereg_file = root / args.prereg
    text = prereg_file.read_text(encoding="utf-8") if prereg_file.is_file() else ""
    per_cell, plan_digest = results_e4.parse_prereg_fields(text)
    status = results_e4.committed_status(
        results_e4.prereg_status(root, args.prereg), lock_commit(root, args.prereg)
    )
    plan = None
    plan_path = root / PLAN
    if plan_path.is_file():
        inputs[PLAN] = results_e4.sha256_file(plan_path)
        plan = results_e4.check_against_plan(
            rows,
            read_json_object(plan_path),
            sha256=inputs[PLAN],
            recorded_sha256=plan_digest,
            planned_runs_per_cell=per_cell,
            e1_arms=e1_arms(root),
        )
    failures = None
    if (root / FAILURES).is_file():
        failures = results_e4.load_jsonl_objects(root / FAILURES)
        inputs[FAILURES] = results_e4.sha256_file(root / FAILURES)
    e1_tasks, e1_sources = e1_task_ids(root)
    for rel in [*e1_sources, args.prereg, LOCK]:
        if (root / rel).is_file():
            inputs[rel] = results_e4.sha256_file(root / rel)
    facts = run_code_facts(root, status.freeze_commit, rows)
    problems, deviations, hashes, dirty = analysis_code_state(root, status.freeze_commit)
    provenance = {
        "git_sha": git_sha(root),
        "command": " ".join(["python", "tools/analyze_e4.py", *argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": dict(sorted(inputs.items())),
        "freeze_commit": status.freeze_commit,
        "analysis_code": hashes,
        "uncommitted_analysis_code": dirty,
        "run_git_shas": sorted(facts.commits),
        "environment": {
            "python": platform.python_version(),
            "numpy": version("numpy"),
            "scipy": version("scipy"),
        },
    }
    artifact = results_e4.build_results(
        rows,
        [b.record for b in banked],
        valid_types=valid,
        prereg=status,
        plan=plan,
        e1_tasks=e1_tasks,
        split_tasks=split_e4_tasks(root),
        failures=failures,
        run_code_facts=facts,
        analysis_code=problems,
        code_deviations=deviations,
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
    except (OSError, ValueError) as exc:  # ValueError includes ConfirmatoryRefusedError
        print(f"E4: {exc}", file=sys.stderr)
        return 1
    results_e4.write_strict_json(out, artifact)
    kind = "confirmatory" if artifact["confirmatory"] else "exploratory"
    label = " SYNTHETIC" if artifact["synthetic"] else ""
    print(
        f"E4: wrote {out} ({kind}{label}): {artifact['runs']['banked']} runs on "
        f"{len(artifact['tasks'])} held-out tasks"
    )
    for reason in artifact["confirmatory_blockers"]:
        print(f"  not confirmatory: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
