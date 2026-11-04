"""Preregistration chain: ``freeze`` a file and ``verify`` integrity (rule 2, gate G11).

``prereg/LOCK.json`` is an append-only hash chain. Each entry records a
preregistration file, its SHA-256, the previous entry's hash, and its own hash
``sha256(prev + "\\n" + file + "\\n" + sha256)``. A file is frozen at the first
commit that contains its LOCK entry.

``verify`` checks that:

1. the chain is intact and every entry's file exists with its locked hash;
2. the chain is append-only across history: every committed version of
   ``LOCK.json`` (oldest first) is an exact prefix of the next version and of the
   working tree's, so no frozen entry is ever dropped, reordered, or rewritten;
3. no frozen file changed in any commit after its freeze commit;
4. every amendment (a file with an ``Amends:`` line) cites a frozen original;
5. every confirmatory artifact (a JSON file under ``artifacts/`` with
   ``"confirmatory": true``) names a frozen ``prereg`` with the matching
   ``prereg_sha256``, and its first commit is a strict descendant of that
   preregistration's freeze commit, so the preregistration predates the data;
6. the raw data behind a confirmatory artifact of experiment ``eN`` (one under
   ``artifacts/eN/`` or ``artifacts/studies/eN/``) come after that freeze too:
   every other file under ``artifacts/eN/`` and ``artifacts/studies/eN/runs/`` is
   committed, and its first commit (following renames into those directories) is
   a strict descendant of the freeze commit. Study plans and pilot runs live
   outside these directories and may predate the freeze.

A shallow clone hides the history these checks read, so ``verify`` refuses one.
The history checks assume the linear history this project keeps.

``verify --json`` also reports counts, which ship_check uses to refuse a vacuous
pass when no confirmatory artifact exists yet.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gitutil import (
    GitError,
    commits_touching,
    first_commit,
    git,
    is_strict_ancestor,
    repo_root,
    sha256_file,
    sha256_text,
)

LOCK = "prereg/LOCK.json"
PREREG_NAME = re.compile(r"^prereg/\d{4}-[a-z0-9][a-z0-9-]*\.md$")
AMENDS = re.compile(r"^Amends:\s*(prereg/\S+\.md)\s*$", re.MULTILINE)
EXPERIMENT = re.compile(r"^artifacts/(?:studies/)?(e\d+)/")
GENESIS = "0" * 64
EXAMPLES = 5


@dataclass(frozen=True)
class LockEntry:
    """One frozen preregistration in the hash chain."""

    file: str
    sha256: str
    prev: str
    entry_hash: str
    frozen_at: str


@dataclass(frozen=True)
class LockVersion:
    """``prereg/LOCK.json`` as committed in one commit (no entries if it was deleted)."""

    commit: str
    entries: tuple[LockEntry, ...]


def entry_hash(prev: str, file: str, digest: str) -> str:
    """Return the chain hash for one entry."""
    return sha256_text(f"{prev}\n{file}\n{digest}")


def parse_lock(text: str) -> list[LockEntry]:
    """Parse the text of a ``LOCK.json``; raises ValueError, KeyError, or TypeError."""
    data = json.loads(text)
    return [LockEntry(**item) for item in data["entries"]]


def load_lock(root: Path) -> list[LockEntry]:
    """Load ``prereg/LOCK.json``; a missing file is an empty chain."""
    path = root / LOCK
    if not path.is_file():
        return []
    return parse_lock(path.read_text(encoding="utf-8"))


def write_lock(root: Path, entries: Sequence[LockEntry]) -> None:
    """Write the chain back to ``prereg/LOCK.json``."""
    payload = {"schema": "receipts.prereg-lock/1", "entries": [asdict(e) for e in entries]}
    (root / LOCK).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def freeze(root: Path, rel: str, today: str) -> LockEntry:
    """Append ``rel`` to the chain. Refuses names outside the convention and refreezes."""
    if not PREREG_NAME.match(rel):
        raise ValueError(f"{rel} does not match prereg/NNNN-<slug>.md")
    entries = load_lock(root)
    if any(e.file == rel for e in entries):
        raise ValueError(f"{rel} is already frozen; write a dated amendment instead")
    digest = sha256_file(root / rel)
    prev = entries[-1].entry_hash if entries else GENESIS
    entry = LockEntry(rel, digest, prev, entry_hash(prev, rel, digest), today)
    write_lock(root, [*entries, entry])
    return entry


def experiment_of(rel: str) -> str | None:
    """Return the experiment id (for example ``e1``) of an artifact path, or None."""
    match = EXPERIMENT.match(rel)
    return match.group(1) if match else None


def data_roots(experiment: str) -> tuple[str, str]:
    """The directories whose files are an experiment's confirmatory data."""
    return (f"artifacts/{experiment}/", f"artifacts/studies/{experiment}/runs/")


@dataclass
class VerifyResult:
    """Outcome of ``verify``."""

    problems: list[str] = field(default_factory=list)
    frozen: int = 0
    drafts: list[str] = field(default_factory=list)
    confirmatory_artifacts: list[str] = field(default_factory=list)
    confirmatory_data: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no problem was found."""
        return not self.problems


def _has_commits(root: Path) -> bool:
    try:
        git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    except GitError:
        return False
    return True


def lock_history(root: Path, result: VerifyResult) -> list[LockVersion]:
    """Return every committed version of ``LOCK.json``, oldest first.

    A commit that deleted the file is a version with no entries. A version that
    does not parse is reported as a problem and left out.
    """
    if not _has_commits(root):
        return []
    shas = git(root, "log", "--format=%H", "--reverse", "--topo-order", "--", LOCK).split()
    versions: list[LockVersion] = []
    for sha in shas:
        try:
            text = git(root, "show", f"{sha}:{LOCK}")
        except GitError:
            versions.append(LockVersion(sha, ()))
            continue
        try:
            versions.append(LockVersion(sha, tuple(parse_lock(text))))
        except (KeyError, TypeError, ValueError) as exc:
            result.problems.append(f"{LOCK} at commit {sha[:12]} is unreadable: {exc}")
    return versions


def _dropped(old: Sequence[LockEntry], new: Sequence[LockEntry]) -> list[str]:
    """Return the files of ``old`` entries that ``new`` does not keep in place."""
    for index, entry in enumerate(old):
        if index >= len(new) or new[index] != entry:
            return [e.file for e in old[index:]]
    return []


def _check_history(
    history: Sequence[LockVersion], current: Sequence[LockEntry], result: VerifyResult
) -> None:
    previous: Sequence[LockEntry] = ()
    for version in history:
        dropped = _dropped(previous, version.entries)
        if dropped:
            result.problems.append(
                f"{LOCK} at commit {version.commit[:12]} drops or rewrites frozen entries: "
                + ", ".join(dropped)
            )
        previous = version.entries
    dropped = _dropped(previous, current)
    if dropped:
        result.problems.append(
            f"{LOCK} in the working tree drops or rewrites frozen entries: " + ", ".join(dropped)
        )


def _freeze_commit(history: Sequence[LockVersion], rel: str) -> str | None:
    """Return the first commit whose LOCK.json lists ``rel``."""
    for version in history:
        if any(e.file == rel for e in version.entries):
            return version.commit
    return None


def _check_chain(
    root: Path,
    entries: Sequence[LockEntry],
    history: Sequence[LockVersion],
    result: VerifyResult,
) -> None:
    prev = GENESIS
    for entry in entries:
        if entry.prev != prev or entry.entry_hash != entry_hash(prev, entry.file, entry.sha256):
            result.problems.append(f"hash chain broken at {entry.file}")
        prev = entry.entry_hash
        path = root / entry.file
        if not path.is_file():
            result.problems.append(f"{entry.file} is frozen but missing")
            continue
        if sha256_file(path) != entry.sha256:
            result.problems.append(f"{entry.file} changed after it was frozen")
        freeze_sha = _freeze_commit(history, entry.file)
        if freeze_sha is None:
            result.problems.append(f"{entry.file} is in LOCK.json but the lock is not committed")
            continue
        added = first_commit(root, entry.file)
        if added is None or not (
            added == freeze_sha or is_strict_ancestor(root, added, freeze_sha)
        ):
            result.problems.append(f"{entry.file} was not committed with or before its freeze")
        if commits_touching(root, entry.file, freeze_sha):
            result.problems.append(f"{entry.file} was modified in a commit after its freeze")


def _check_amendments(root: Path, frozen: set[str], result: VerifyResult) -> None:
    for path in sorted((root / "prereg").glob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel == "prereg/README.md":
            continue
        if not PREREG_NAME.match(rel):
            result.problems.append(f"{rel} does not match prereg/NNNN-<slug>.md")
            continue
        if rel not in frozen:
            result.drafts.append(rel)
        for cited in AMENDS.findall(path.read_text(encoding="utf-8")):
            if cited not in frozen:
                result.problems.append(f"{rel} amends {cited}, which is not frozen")


def _iter_json_artifacts(root: Path) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for path in sorted((root / "artifacts").rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        try:
            items.append((rel, json.loads(path.read_text(encoding="utf-8"))))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return items


def _repo_files(root: Path, pathspecs: Sequence[str]) -> list[str]:
    """Tracked files plus untracked files that are not ignored, present on disk."""
    out = git(
        root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *pathspecs
    )
    return sorted({p for p in out.split("\0") if p and (root / p).is_file()})


def _add_commits(root: Path, pathspecs: Sequence[str]) -> dict[str, list[str]]:
    """Map each path under ``pathspecs`` to every commit that added it there.

    Renames count as additions here (``--no-renames``); ``_rename_targets`` tells
    which additions were renames, so their history can be followed.
    """
    if not _has_commits(root):
        return {}
    out = git(
        root,
        "log",
        "--no-renames",
        "--diff-filter=A",
        "--name-only",
        "-z",
        "--format=%x01%H",
        "--",
        *pathspecs,
    )
    adds: dict[str, list[str]] = {}
    for record in out.split("\x01"):
        sha, _, names = record.partition("\0")
        for name in names.split("\0"):
            path = name.lstrip("\n")
            if sha and path:
                adds.setdefault(path, []).append(sha)
    return adds


def _rename_targets(root: Path, commit: str) -> set[str]:
    """Return the paths that ``commit`` created by renaming another path."""
    try:
        out = git(
            root,
            "-c",
            "diff.renameLimit=0",
            "diff",
            "--find-renames",
            "--name-status",
            "-z",
            "--diff-filter=R",
            f"{commit}^1",
            commit,
        )
    except GitError:  # a root commit has no parent to rename from
        return set()
    # With --diff-filter=R every record is three fields: status, source, destination.
    tokens = out.split("\0")
    return {tokens[i + 2] for i in range(0, len(tokens) - 2, 3) if tokens[i].startswith("R")}


def _listing(paths: Sequence[str]) -> str:
    shown = ", ".join(paths[:EXAMPLES])
    return shown + (f" and {len(paths) - EXAMPLES} more" if len(paths) > EXAMPLES else "")


def _check_data(
    root: Path,
    experiment: str,
    cited: str,
    freeze_sha: str,
    skip: set[str],
    result: VerifyResult,
) -> None:
    """Require every raw data file of ``experiment`` to be first committed after the freeze."""
    roots = data_roots(experiment)
    files = [p for p in _repo_files(root, roots) if p not in skip]
    adds = _add_commits(root, roots)
    renamed: dict[str, set[str]] = {}
    after: dict[str, bool] = {}
    uncommitted: list[str] = []
    early: list[str] = []
    for path in files:
        origins = list(adds.get(path, []))
        if not origins:
            uncommitted.append(path)
            continue
        for sha in list(origins):
            if sha not in renamed:
                renamed[sha] = _rename_targets(root, sha)
            if path in renamed[sha]:
                followed = first_commit(root, path)
                if followed is not None:
                    origins.append(followed)
                break
        for sha in origins:
            if sha not in after:
                after[sha] = is_strict_ancestor(root, freeze_sha, sha)
        if not all(after[sha] for sha in origins):
            early.append(path)
        if path not in result.confirmatory_data:
            result.confirmatory_data.append(path)
    if uncommitted:
        result.problems.append(
            f"{len(uncommitted)} confirmatory data file(s) of {experiment} are not committed, "
            f"so their timing cannot be verified: {_listing(uncommitted)}"
        )
    if early:
        result.problems.append(
            f"{len(early)} confirmatory data file(s) of {experiment} were first committed at or "
            f"before {cited} was frozen: {_listing(early)}"
        )


def _check_artifacts(
    root: Path,
    entries: Sequence[LockEntry],
    history: Sequence[LockVersion],
    result: VerifyResult,
) -> None:
    locked = {e.file: e for e in entries}
    bounds: dict[str, set[tuple[str, str]]] = {}
    for rel, data in _iter_json_artifacts(root):
        if not (isinstance(data, dict) and data.get("confirmatory") is True):
            continue
        result.confirmatory_artifacts.append(rel)
        cited = data.get("prereg")
        if not isinstance(cited, str) or cited not in locked:
            result.problems.append(f"{rel} is confirmatory but cites no frozen prereg")
            continue
        if data.get("prereg_sha256") != locked[cited].sha256:
            result.problems.append(f"{rel} prereg_sha256 does not match {cited}")
        artifact_first = first_commit(root, rel)
        freeze_sha = _freeze_commit(history, cited)
        if artifact_first is None:
            result.problems.append(f"{rel} is not committed, so its timing cannot be verified")
        elif freeze_sha is None or not is_strict_ancestor(root, freeze_sha, artifact_first):
            result.problems.append(f"{rel} first commit does not come after {cited} was frozen")
        experiment = experiment_of(rel)
        if experiment is not None and freeze_sha is not None:
            bounds.setdefault(experiment, set()).add((cited, freeze_sha))
    skip = set(result.confirmatory_artifacts)
    for experiment in sorted(bounds):
        for cited, freeze_sha in sorted(bounds[experiment]):
            _check_data(root, experiment, cited, freeze_sha, skip, result)
    result.confirmatory_data.sort()


def verify(root: Path) -> VerifyResult:
    """Run every preregistration integrity check."""
    result = VerifyResult()
    try:
        entries = load_lock(root)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result.problems.append(f"{LOCK} is unreadable: {exc}")
        return result
    result.frozen = len(entries)
    if git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        result.problems.append(
            "this is a shallow clone, so the preregistration history cannot be verified "
            "(run git fetch --unshallow)"
        )
        return result
    history = lock_history(root, result)
    _check_history(history, entries, result)
    _check_chain(root, entries, history, result)
    _check_amendments(root, {e.file for e in entries}, result)
    _check_artifacts(root, entries, history, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ``freeze <file>`` or ``verify [--json]``."""
    parser = argparse.ArgumentParser(description="Preregistration hash chain.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_freeze = sub.add_parser("freeze")
    p_freeze.add_argument("file")
    p_freeze.add_argument("--date", required=True, help="freeze date, YYYY-MM-DD")
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    if args.command == "freeze":
        entry = freeze(root, args.file, args.date)
        print(f"frozen {entry.file} sha256={entry.sha256}; commit {LOCK} with it now")
        return 0
    result = verify(root)
    if args.json:
        print(json.dumps(asdict(result) | {"ok": result.ok}, indent=2))
    else:
        for problem in result.problems:
            print(f"problem: {problem}")
        print(
            f"frozen={result.frozen} drafts={len(result.drafts)} "
            f"confirmatory_artifacts={len(result.confirmatory_artifacts)}"
        )
        print("PREREG-VERIFY: " + ("PASS" if result.ok else f"FAIL {len(result.problems)}"))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
