"""Preregistration chain: ``freeze`` a file and ``verify`` integrity (rule 2, gate G11).

``prereg/LOCK.json`` is an append-only hash chain. Each entry records a
preregistration file, its SHA-256, the previous entry's hash, and its own hash
``sha256(prev + "\\n" + file + "\\n" + sha256)``. A file is frozen at the first
commit that contains its LOCK entry.

``verify`` checks that:

1. the chain is intact and every entry's file exists with its locked hash;
2. no frozen file changed in any commit after its freeze commit;
3. every amendment (a file with an ``Amends:`` line) cites a frozen original;
4. every confirmatory artifact (a JSON file under ``artifacts/`` with
   ``"confirmatory": true``) names a frozen ``prereg`` with the matching
   ``prereg_sha256``, and its first commit is a strict descendant of that
   preregistration's freeze commit, so the preregistration predates the data.

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
GENESIS = "0" * 64


@dataclass(frozen=True)
class LockEntry:
    """One frozen preregistration in the hash chain."""

    file: str
    sha256: str
    prev: str
    entry_hash: str
    frozen_at: str


def entry_hash(prev: str, file: str, digest: str) -> str:
    """Return the chain hash for one entry."""
    return sha256_text(f"{prev}\n{file}\n{digest}")


def load_lock(root: Path) -> list[LockEntry]:
    """Load ``prereg/LOCK.json``; a missing file is an empty chain."""
    path = root / LOCK
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [LockEntry(**item) for item in data["entries"]]


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


@dataclass
class VerifyResult:
    """Outcome of ``verify``."""

    problems: list[str] = field(default_factory=list)
    frozen: int = 0
    drafts: list[str] = field(default_factory=list)
    confirmatory_artifacts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no problem was found."""
        return not self.problems


def _freeze_commit(root: Path, rel: str) -> str | None:
    """Return the first commit whose LOCK.json lists ``rel``."""
    shas = git(root, "log", "--format=%H", "--reverse", "--", LOCK).split()
    for sha in shas:
        try:
            content = git(root, "show", f"{sha}:{LOCK}")
        except GitError:
            continue
        if any(item.get("file") == rel for item in json.loads(content).get("entries", [])):
            return sha
    return None


def _check_chain(root: Path, entries: Sequence[LockEntry], result: VerifyResult) -> None:
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
        freeze_sha = _freeze_commit(root, entry.file)
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


def _check_artifacts(root: Path, entries: Sequence[LockEntry], result: VerifyResult) -> None:
    locked = {e.file: e for e in entries}
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
        freeze_sha = _freeze_commit(root, cited)
        if artifact_first is None:
            result.problems.append(f"{rel} is not committed, so its timing cannot be verified")
        elif freeze_sha is None or not is_strict_ancestor(root, freeze_sha, artifact_first):
            result.problems.append(f"{rel} first commit does not come after {cited} was frozen")


def verify(root: Path) -> VerifyResult:
    """Run every preregistration integrity check."""
    result = VerifyResult()
    try:
        entries = load_lock(root)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result.problems.append(f"{LOCK} is unreadable: {exc}")
        return result
    result.frozen = len(entries)
    _check_chain(root, entries, result)
    _check_amendments(root, {e.file for e in entries}, result)
    _check_artifacts(root, entries, result)
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
