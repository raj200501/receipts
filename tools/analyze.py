"""Run the preregistered E1 and E2 analysis (prereg/0001-e1-main-study.md, section 5).

    python tools/analyze.py e1   # artifacts/e1/results.json from artifacts/e1/runs.jsonl,
                                 # artifacts/e0/seeded_eval.json, artifacts/studies/e1/plan.json,
                                 # and artifacts/studies/e1/failures.jsonl
    python tools/analyze.py e2   # artifacts/e2/mechanism.json from the same inputs and the
                                 # banked ledgers under artifacts/studies/e1/runs/

The computation is :mod:`receipts.study.results`. This tool reads the inputs, checks
that the preregistration is frozen (:func:`prereg_status`: listed in
``prereg/LOCK.json`` with its current SHA-256, an intact hash chain, the same SHA-256 in
the lock entry committed at the freeze commit and at HEAD, and neither file with an
uncommitted change), that the analysis code that runs is the code under ``--root`` and
is committed there, and whether it changed after the freeze commit, at the analysis
checkout or at the commit the rows were banked at (:func:`code_checks`; a change is the
deviation ``analysis_code_changed`` that section 5 requires to be reported), and writes
the artifact as strict JSON with provenance: the git SHA, the command, the time, the
SHA-256 of every input file (each banked ``run.json`` included), the preregistration's
path and SHA-256, the SHA-256 of every analysis code file that ran, and the Python and
library versions.

Both commands check that the rows are the banking of exactly the banked runs
(:func:`receipts.study.results.banking_checks`: every banked ``run.json`` under
``artifacts/studies/e1/runs/`` has a row that matches it, every row has a banked run,
and ``artifacts/e1/runs.provenance.json`` records the SHA-256 of the rows file), check
the rows against the study plan, the banked failure log, and the preregistration's
``planned_runs_per_config:`` and ``plan_sha256:`` lines
(:func:`receipts.study.results.run_checks`; a missing line is a blocker), and check the
rows' instrument and run provenance (:func:`receipts.study.results.provenance_checks`)
against the held-out evaluation and the freeze commit (:func:`freeze_state`: the commit
that added the preregistration's lock entry, and the hash of each task directory at that
commit, :func:`committed_tree_sha256`), so a problem that keeps E1 from being
confirmatory keeps E2 from it too. Section 5 defines the analysis as these two commands
with their default arguments: a confirmatory artifact reads every input at its default
path (:func:`input_checks`), and the held-out evaluation without uncommitted changes.

Every path is relative to ``--root`` (default: this repository), and so are the git
checks. ``--n-boot`` exists for tests: any value other than the preregistered 2000 makes
the artifact non-confirmatory. A synthetic artifact is never written to this
repository's gate paths (``artifacts/e1/results.json``, ``artifacts/e2/mechanism.json``).
Errors (a missing or malformed input) print one line and exit with status 2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any

import prereg
import receipts
import receipts.analysis
import receipts.evaluation.mechanism
import receipts.ledger.events
import receipts.study.aggregate
import receipts.study.rescore
import receipts.study.spec
from gitutil import GitError, git, sha256_file
from receipts.study import results

ROOT = Path(__file__).resolve().parents[1]
RUNS = "artifacts/e1/runs.jsonl"
#: The record ``tools/bank_study.py e1`` writes beside the rows (``rows_sha256``).
ROWS_PROVENANCE = "artifacts/e1/runs.provenance.json"
SEEDED = "artifacts/e0/seeded_eval.json"
PLAN = "artifacts/studies/e1/plan.json"
FAILURES = "artifacts/studies/e1/failures.jsonl"
RUN_DIRS = "artifacts/studies/e1/runs"
TASKS = "bench/tasks"
E1_OUT = "artifacts/e1/results.json"
E2_OUT = "artifacts/e2/mechanism.json"
#: The code that turns banked runs into rows, besides the instrument (whose git trees
#: the rows record and the analysis compares with the evaluated ones): the banking
#: tool, the rescoring, the row builder, the study spec it checks mitigations against,
#: the task spec and tree hash it reads requirement texts and task files with, and the
#: E0 modules the rescoring imports to record the instrument and read the verdict names
#: (outside the rows' instrument record since DECISIONS D47).
BANKING_CODE: tuple[str, ...] = (
    "tools/bank_study.py",
    "src/receipts/study/rescore.py",
    "src/receipts/study/aggregate.py",
    "src/receipts/study/spec.py",
    "src/receipts/bench/spec.py",
    "src/receipts/bench/hashing.py",
    "src/receipts/evaluation/e0.py",
    "src/receipts/evaluation/facts.py",
    "src/receipts/evaluation/seeded.py",
)
#: The analysis code, checked for uncommitted changes and for changes after the freeze:
#: the code this tool runs and the banking code (:data:`BANKING_CODE`), because the
#: rows' outcomes are computed when the runs are banked (section 5).
ANALYSIS_CODE: tuple[str, ...] = (
    "tools/analyze.py",
    "src/receipts/study/results.py",
    "src/receipts/study/rescore.py",
    "src/receipts/study/aggregate.py",
    "src/receipts/study/spec.py",
    "src/receipts/analysis",
    "src/receipts/evaluation/mechanism.py",
    "src/receipts/ledger/events.py",
    "tools/bank_study.py",
    "src/receipts/bench/spec.py",
    "src/receipts/bench/hashing.py",
    "src/receipts/evaluation/e0.py",
    "src/receipts/evaluation/facts.py",
    "src/receipts/evaluation/seeded.py",
)
#: A full git commit id (SHA-1 or SHA-256); anything else is never passed to git.
_COMMIT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


# Inputs ---------------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object; raises OSError or ValueError (naming the file)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not valid JSON ({exc})") from exc
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


def load_seeded(root: Path, rel: str) -> tuple[dict[str, Any], str]:
    """The seeded evaluation at ``rel`` and the SHA-256 of the bytes it was parsed from.

    Raises:
        OSError: The file cannot be read.
        ValueError: It is not a JSON object.
    """
    raw = (root / rel).read_bytes()
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{rel} is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{rel} is not a JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def read_failures(root: Path, rel: str) -> list[dict[str, Any]] | None:
    """The entries of the banked failure log at ``rel``, or None when none is banked."""
    path = root / rel
    return read_jsonl(path) if path.is_file() else None


def lock_entry_at(root: Path, commit: str, rel: str) -> Mapping[str, Any] | None:
    """The first entry for ``rel`` in ``prereg/LOCK.json`` as committed at ``commit``.

    None when that commit has no readable lock or its lock does not list ``rel``.
    """
    try:
        data = json.loads(git(root, "show", f"{commit}:{prereg.LOCK}"))
    except (GitError, json.JSONDecodeError):
        return None
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None
    return next((e for e in entries if isinstance(e, dict) and e.get("file") == rel), None)


def lock_commit(root: Path, rel: str) -> tuple[str, object] | None:
    """The first commit whose ``prereg/LOCK.json`` lists ``rel`` (the freeze commit) and
    the ``sha256`` its entry for ``rel`` records; None when no commit lists it.

    Commits are read oldest first in topological order (``git log --reverse
    --topo-order``, as ``tools/prereg.py`` and ``tools/ship_check.py`` read the lock
    history), so commit dates cannot change which commit froze the file.
    """
    try:
        shas = git(
            root, "log", "--format=%H", "--reverse", "--topo-order", "--", prereg.LOCK
        ).split()
    except GitError:
        return None
    for sha in shas:
        entry = lock_entry_at(root, sha, rel)
        if entry is not None:
            return sha, entry.get("sha256")
    return None


def freeze_commit(root: Path, rel: str) -> str | None:
    """The first commit whose ``prereg/LOCK.json`` lists ``rel`` (:func:`lock_commit`)."""
    found = lock_commit(root, rel)
    return None if found is None else found[0]


def prereg_status(root: Path, rel: str) -> results.PreregInfo:
    """Whether ``rel`` is frozen: in an intact, committed lock chain with its current hash.

    Frozen (section 11, item 1) means: the working-tree ``prereg/LOCK.json`` has an
    intact hash chain and lists ``rel`` with the file's current SHA-256; the lock entry
    committed at the freeze commit (:func:`lock_commit`) and the one committed at HEAD
    record that same SHA-256, so an edited file whose lock entry was edited to match it
    is not frozen, committed or not; and neither ``prereg/LOCK.json`` nor ``rel`` has an
    uncommitted change.

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
    else:
        first = lock_commit(root, rel)
        if first is None:
            problems.append(
                f"the {prereg.LOCK} entry for {rel} is not committed, so it is not frozen"
            )
        else:
            commit, locked = first
            if locked != digest:
                problems.append(
                    f"the {prereg.LOCK} entry for {rel} committed at the freeze commit "
                    f"{commit[:12]} records SHA-256 {str(locked)[:12]}, not the file's "
                    f"{digest[:12]}, so the file or its lock entry was edited after the freeze"
                )
            head = lock_entry_at(root, "HEAD", rel)
            if head is None or head.get("sha256") != digest:
                problems.append(
                    f"the {prereg.LOCK} committed at HEAD does not list {rel} with its "
                    f"current SHA-256 {digest[:12]}"
                )
    dirty = uncommitted(root, [prereg.LOCK, rel])
    if dirty:
        problems.append(
            "uncommitted changes to "
            + ", ".join(dirty)
            + ", so the frozen state read here is not the committed one"
        )
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


def load_banked(
    root: Path, runs_rel: str, rows_rel: str
) -> tuple[results.BankedRuns, dict[str, str]]:
    """The banked runs under ``runs_rel`` and the banking record, with the SHA-256 of
    every file read, by its path relative to ``root`` (for the provenance's inputs).

    Every ``<run_id>/run.json`` under ``runs_rel`` is a banked run, as
    ``tools/bank_study.py e1`` takes them. The banking record is :data:`ROWS_PROVENANCE`
    (None when absent); ``rows_rel`` is the rows file, whose SHA-256 it must record.

    Raises:
        OSError: A file cannot be read.
        ValueError: A ``run.json`` or the banking record is not a JSON object, or a
            ``run.json`` records another run than the one its directory names.
    """
    records: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for path in sorted((root / runs_rel).glob("*/run.json")):
        name = path.parent.name
        record = read_json(path)
        if record.get("run_id") != name:
            raise ValueError(
                f"{runs_rel}/{name}/run.json records run {record.get('run_id')!r}, not {name}"
            )
        records[name] = record
        hashes[f"{runs_rel}/{name}/run.json"] = sha256_file(path)
    banking_path = root / ROWS_PROVENANCE
    banking = read_json(banking_path) if banking_path.is_file() else None
    if banking is not None:
        hashes[ROWS_PROVENANCE] = sha256_file(banking_path)
    banked = results.BankedRuns(
        runs_dir=runs_rel,
        records=records,
        rows_path=rows_rel,
        rows_sha256=sha256_file(root / rows_rel),
        banking_path=ROWS_PROVENANCE,
        banking=banking,
    )
    return banked, hashes


def load_e1_inputs(
    root: Path, args: argparse.Namespace
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    str,
    results.PreregInfo,
    results.StudyPlan | None,
    list[dict[str, Any]] | None,
]:
    """The rows, the seeded evaluation and its SHA-256, the preregistration status, the
    plan (or None), and the banked failure log (or None), from the paths in ``args``."""
    rows = read_jsonl(root / args.runs)
    evaluation, evaluation_sha = load_seeded(root, args.seeded)
    info = prereg_status(root, args.prereg)
    return (
        rows,
        evaluation,
        evaluation_sha,
        info,
        load_plan(root, args.plan),
        read_failures(root, args.failures),
    )


# The freeze commit's task files ---------------------------------------------------------


def _blob_contents(root: Path, objects: Sequence[str]) -> dict[str, bytes]:
    """The bytes of each git blob in ``objects`` (``git cat-file --batch``).

    Raises:
        GitError: git fails or an object is not a blob.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(f"{obj}\n" for obj in objects).encode(),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git cat-file --batch failed: {proc.stderr.decode(errors='replace')}")
    out, pos, blobs = proc.stdout, 0, {}
    for obj in objects:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode(errors="replace").split()
        if len(header) != 3 or header[1] != "blob":
            raise GitError(f"git object {obj} is not a readable blob")
        size = int(header[2])
        blobs[header[0]] = out[end + 1 : end + 1 + size]
        pos = end + 1 + size + 1
    return blobs


def committed_tree_sha256(root: Path, commit: str, rel: str) -> str | None:
    """The tree hash of directory ``rel`` as committed at ``commit``, or None without files.

    It is the hash ``tools/run_study.py`` records as a run's ``task_tree_sha256``
    (:func:`receipts.bench.hashing.tree_sha256`, byte for byte the
    ``tools/ship_check.py`` ``tree_sha256``): SHA-256 over
    ``f"{path}\\0{sha256 of the file}\\n"`` for every file under the directory, with
    paths relative to it and sorted as path objects. Here the files are the git blobs at
    ``commit`` instead of a checkout, so a later edit to the working tree cannot change
    it.

    Raises:
        GitError: git cannot list or read the tree at ``commit``.
        ValueError: The directory holds a symbolic link or a submodule, which a
            checkout's hash would not read as the committed file.
    """
    prefix = rel.strip("/") + "/"
    listing = git(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", prefix)
    entries: list[tuple[str, str]] = []
    for item in listing.split("\0"):
        meta, tab, path = item.partition("\t")
        if not tab or not path.startswith(prefix):
            continue
        mode, kind, obj = meta.split()
        if kind != "blob" or mode == "120000":
            what = "symbolic link" if mode == "120000" else kind
            raise ValueError(f"{path} at {commit[:12]} is a {what}, not a file")
        entries.append((path[len(prefix) :], obj))
    if not entries:
        return None
    blobs = _blob_contents(root, sorted({obj for _, obj in entries}))
    digest = hashlib.sha256()
    for name, obj in sorted(entries, key=lambda entry: PurePosixPath(entry[0]).parts):
        digest.update(f"{name}\0{hashlib.sha256(blobs[obj]).hexdigest()}\n".encode())
    return digest.hexdigest()


def _task_dir_name(task_id: str) -> bool:
    """True when ``task_id`` names one directory (no separator, not ``.`` or ``..``)."""
    return (
        bool(task_id) and task_id not in (".", "..") and "/" not in task_id and "\\" not in task_id
    )


def freeze_state(
    root: Path, info: results.PreregInfo, task_ids: Sequence[str]
) -> results.FreezeState:
    """The freeze commit of ``info`` and the hash of each task directory at that commit.

    The freeze commit is the first commit whose ``prereg/LOCK.json`` lists the
    preregistration (:func:`freeze_commit`), known only for a frozen preregistration. A
    task the commit does not hold, whose id is not one directory name, or whose files
    cannot be hashed gets None, which the analysis reports as a blocker.
    """
    commit = freeze_commit(root, info.path) if info.frozen else None
    if commit is None:
        return results.FreezeState(None)
    trees: dict[str, str | None] = {}
    for task_id in sorted(set(task_ids)):
        tree = None
        if _task_dir_name(task_id):
            try:
                tree = committed_tree_sha256(root, commit, f"{TASKS}/{task_id}")
            except (GitError, ValueError):
                tree = None
        trees[task_id] = tree
    return results.FreezeState(commit, trees)


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


def changed_since(root: Path, commit: str, paths: Sequence[str], to: str = "HEAD") -> list[str]:
    """Paths under ``paths`` that differ between ``commit`` and ``to`` (default HEAD).

    Raises:
        GitError: git cannot compare the two commits.
    """
    out = git(root, "diff", "--name-only", commit, to, "--", *paths)
    return sorted(p for p in out.splitlines() if p)


def _listing(paths: Sequence[str], limit: int = 5) -> str:
    """The first ``limit`` paths, comma-separated, with ``...`` when there are more."""
    return ", ".join(paths[:limit]) + (", ..." if len(paths) > limit else "")


def running_code_problems(root: Path) -> list[str]:
    """A blocker when the analysis code that runs is not the code under ``root``.

    The commit checks of :func:`code_checks` read the files under ``--root``, so they
    describe the code that runs only when every file that runs (:func:`code_files`)
    is, byte for byte, the file at the same path under ``root``. A file run from
    outside a ``src/`` layout has no such path and always differs.
    """
    differ = sorted(
        rel
        for rel, digest in code_hashes().items()
        if PurePosixPath(rel).is_absolute()
        or not (root / rel).is_file()
        or sha256_file(root / rel) != digest
    )
    if not differ:
        return []
    return [
        "the analysis code that runs differs from the files under --root, so the checks "
        "of their commit state do not describe it: " + _listing(differ)
    ]


def banking_commits(
    rows: Sequence[Mapping[str, Any]], banking: Mapping[str, Any] | None
) -> list[str]:
    """The commits the rows were banked at, sorted: each row's ``instrument.commit`` and
    the banking record's ``provenance.git_sha`` (both HEAD of the banking checkout)."""
    commits: set[str] = set()
    for row in rows:
        record = row.get("instrument")
        commit = record.get("commit") if isinstance(record, Mapping) else None
        if isinstance(commit, str) and commit:
            commits.add(commit)
    prov = banking.get("provenance") if isinstance(banking, Mapping) else None
    sha = prov.get("git_sha") if isinstance(prov, Mapping) else None
    if isinstance(sha, str) and sha:
        commits.add(sha)
    return sorted(commits)


def banking_code_checks(
    root: Path, frozen_at: str, banked_at: Sequence[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Blockers and deviations from the banking code at each banking commit (section 5).

    The rows' outcomes are computed when the runs are banked, by the banking code
    (:data:`BANKING_CODE`) of the banking commit. Any file of it that differs between
    the freeze commit and a banking commit is the deviation ``analysis_code_changed``
    (``stage: banking``), also when the analysis checkout holds the code of the freeze
    commit again. A banking commit that is not a commit id, or that git cannot compare
    with the freeze commit, blocks a confirmatory artifact.

    Returns:
        ``(blockers, deviations)``.
    """
    blockers: list[str] = []
    deviations: list[dict[str, Any]] = []
    for commit in banked_at:
        changed: list[str] | None = None
        if _COMMIT_ID.match(commit):
            try:
                changed = changed_since(root, frozen_at, BANKING_CODE, to=commit)
            except GitError:
                changed = None
        if changed is None:
            blockers.append(
                f"the rows were banked at {commit[:40]!r}, which is not a commit of this "
                f"repository that git can compare with the freeze commit {frozen_at[:12]}, so "
                "the banking code that computed their outcomes is unknown (section 5)"
            )
        elif changed:
            deviations.append(
                {
                    "kind": "analysis_code_changed",
                    "stage": "banking",
                    "prereg_section": "5",
                    "banking_commit": commit,
                    "files": changed,
                    "detail": f"the rows were banked at {commit[:12]} with banking code that "
                    f"differs from the freeze commit {frozen_at[:12]}: "
                    + ", ".join(changed)
                    + "; that code computed every outcome, so the preregistered result is "
                    "the analysis of the runs banked again with the banking code of the "
                    "freeze commit, reported beside this one",
                }
            )
    return blockers, deviations


def code_checks(
    root: Path, info: results.PreregInfo, banked_at: Sequence[str] = ()
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Confirmatory blockers and deviations from the state of the analysis code.

    Args:
        root: The repository the analysis reads (``--root``).
        info: The preregistration status.
        banked_at: The commits the rows were banked at (:func:`banking_commits`).

    Returns:
        ``(blockers, deviations, dirty)``. Blockers: the analysis code that runs is not
        the code under ``root`` (:func:`running_code_problems`); ``root`` is not a git
        repository, or the analysis code (:data:`ANALYSIS_CODE`) has uncommitted
        changes there, so the artifact could not be reproduced from its git SHA; or a
        banking commit cannot be compared with the freeze commit. Deviations
        (``analysis_code_changed``, section 5): analysis code that differs between the
        freeze commit and HEAD (``stage: analysis``), and banking code that differs
        between the freeze commit and a banking commit (:func:`banking_code_checks`).
    """
    blockers = running_code_problems(root)
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
                    "stage": "analysis",
                    "prereg_section": "5",
                    "files": changed,
                    "detail": f"analysis code changed after the freeze commit {frozen_at[:12]}: "
                    + ", ".join(changed)
                    + "; report the results of the code at the freeze commit beside these",
                }
            )
        banking_blockers, banking_deviations = banking_code_checks(root, frozen_at, banked_at)
        blockers += banking_blockers
        deviations += banking_deviations
    return blockers, deviations, dirty


#: The inputs section 5 fixes besides the evaluation and the failure log: argument,
#: default path, and what it holds.
FIXED_INPUTS: tuple[tuple[str, str, str], ...] = (
    ("runs", RUNS, "the rows"),
    ("prereg", results.PREREG_E1, "the preregistration"),
    ("plan", PLAN, "the study plan"),
    ("run_dirs", RUN_DIRS, "the banked runs"),
)


def input_checks(root: Path, args: argparse.Namespace) -> list[str]:
    """Confirmatory blockers from where the inputs came.

    Section 5 defines the analysis as the two commands with their default arguments, so
    a confirmatory artifact reads every input at its default path: the rows, the
    preregistration, the study plan, and the banked runs (:data:`FIXED_INPUTS`); the
    valid types and the instrument check from the held-out G5 evaluation that gate G5
    checks, ``artifacts/e0/seeded_eval.json`` as committed; and the run accounting from
    the banked failure log ``artifacts/studies/e1/failures.jsonl``. Any other path, or
    an evaluation file with uncommitted changes, blocks a confirmatory artifact.
    (Outside a repository :func:`code_checks` already blocks.)
    """
    blockers: list[str] = []
    for name, default, what in FIXED_INPUTS:
        value = getattr(args, name)
        if value != default:
            option = "--" + name.replace("_", "-")
            blockers.append(
                f"{option} reads {what} from {value}, not from {default}; section 5 "
                "defines the analysis with its default arguments"
            )
    if args.seeded != SEEDED:
        blockers.append(
            f"the valid claim types come from {args.seeded}, not from the held-out G5 "
            f"evaluation {SEEDED}"
        )
    if args.failures != FAILURES:
        blockers.append(
            f"the run accounting reads the failure log {args.failures}, not the banked {FAILURES}"
        )
    dirty = uncommitted(root, [args.seeded])
    if dirty:
        blockers.append(
            f"the held-out evaluation {args.seeded} has uncommitted changes, so it is not "
            "the committed evaluation gate G5 checks"
        )
    return blockers


def code_files() -> dict[str, Path]:
    """Every analysis code file this process runs, by its path in the repository.

    This tool is ``tools/analyze.py``; each module is named by its path under ``src/``,
    found from where ``receipts`` was imported, so code imported from a snapshot keeps
    the path it has in a checkout. Every module of ``receipts.analysis`` is included. A
    module outside that ``src/`` keeps its absolute path.
    """
    src = Path(str(receipts.__file__)).resolve().parents[1]
    modules = (
        results,
        receipts.study.rescore,
        receipts.study.aggregate,
        receipts.study.spec,
        receipts.evaluation.mechanism,
        receipts.ledger.events,
    )
    paths = [Path(str(m.__file__)).resolve() for m in modules]
    paths += sorted(Path(str(receipts.analysis.__file__)).resolve().parent.glob("*.py"))
    files: dict[str, Path] = {"tools/analyze.py": Path(__file__).resolve()}
    for path in paths:
        try:
            files["src/" + path.relative_to(src).as_posix()] = path
        except ValueError:
            files[path.as_posix()] = path
    return files


def code_hashes() -> dict[str, str]:
    """SHA-256 of every analysis code file that this process runs (:func:`code_files`)."""
    return {rel: sha256_file(path) for rel, path in code_files().items()}


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


def _checks(
    root: Path,
    args: argparse.Namespace,
    info: results.PreregInfo,
    rows: Sequence[Mapping[str, Any]],
    banked: results.BankedRuns,
) -> tuple[list[str], list[dict[str, Any]], list[str], results.FreezeState]:
    """The code and input blockers, the code deviations, the uncommitted analysis code,
    and the freeze state, shared by both commands."""
    blockers, deviations, dirty = code_checks(root, info, banking_commits(rows, banked.banking))
    blockers += input_checks(root, args)
    freeze = freeze_state(root, info, [str(r.get("task_id")) for r in rows])
    return blockers, deviations, dirty, freeze


def _inputs(
    root: Path, args: argparse.Namespace, banked_files: Mapping[str, str]
) -> dict[str, str]:
    """The SHA-256 of every input file read, by path: the rows, the evaluation, the plan,
    the failure log, the preregistration and its lock, each banked ``run.json``, and the
    banking record."""
    rels = [args.runs, args.seeded, args.plan, args.failures, args.prereg, prereg.LOCK]
    return {**input_hashes(root, rels), **banked_files}


def run_e1(root: Path, args: argparse.Namespace, argv: Sequence[str]) -> int:
    """``e1``: write ``artifacts/e1/results.json``."""
    rows, evaluation, evaluation_sha, info, plan, failures = load_e1_inputs(root, args)
    banked, banked_files = load_banked(root, args.run_dirs, args.runs)
    out = root / args.out
    _refuse_gate_path(out, results.synthetic_flag(rows))
    blockers, deviations, dirty, freeze = _checks(root, args, info, rows, banked)
    artifact = results.e1_results(
        rows,
        evaluation,
        seeded_sha256=evaluation_sha,
        prereg=info,
        plan=plan,
        freeze=freeze,
        failures=failures,
        banked=banked,
        provenance=provenance(root, argv, _inputs(root, args, banked_files), info, dirty),
        settings=results.E1Settings(n_boot=args.n_boot),
        blockers=blockers,
        deviations=deviations,
    )
    write_artifact(out, artifact)
    _report("e1", artifact, f"{len(artifact['configs'])} configuration(s)", args.out)
    return 0


def run_e2(root: Path, args: argparse.Namespace, argv: Sequence[str]) -> int:
    """``e2``: write ``artifacts/e2/mechanism.json``."""
    rows, evaluation, evaluation_sha, info, plan, failures = load_e1_inputs(root, args)
    banked, banked_files = load_banked(root, args.run_dirs, args.runs)
    out = root / args.out
    _refuse_gate_path(out, results.synthetic_flag(rows))
    blockers, deviations, dirty, freeze = _checks(root, args, info, rows, banked)
    runs_dir = root / args.run_dirs

    def load(run_id: str) -> results.RunEvidence:
        return results.load_run_evidence(runs_dir / run_id, root=root)

    artifact = results.e2_mechanism(
        rows,
        load,
        seeded=evaluation,
        seeded_sha256=evaluation_sha,
        prereg=info,
        plan=plan,
        freeze=freeze,
        failures=failures,
        banked=banked,
        provenance=provenance(root, argv, _inputs(root, args, banked_files), info, dirty),
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
    common.add_argument(
        "--seeded", default=SEEDED, help=f"held-out G5 evaluation (default {SEEDED})"
    )
    common.add_argument(
        "--failures", default=FAILURES, help=f"banked failure log (default {FAILURES})"
    )
    common.add_argument("--run-dirs", default=RUN_DIRS, help=f"banked runs (default {RUN_DIRS})")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e1 = sub.add_parser("e1", parents=[common], help="E1 results (RQ1, RQ2)")
    e1.add_argument("--out", default=E1_OUT, help=f"output (default {E1_OUT})")
    e1.add_argument(
        "--n-boot",
        type=int,
        default=results.E1Settings().n_boot,
        help="bootstrap resamples (tests only: any other value is not confirmatory)",
    )
    e2 = sub.add_parser("e2", parents=[common], help="E2 mechanism mix (RQ3)")
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
