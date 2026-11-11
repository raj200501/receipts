"""Small git and file helpers shared by the repository tools (stdlib only)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command fails."""


def git(root: Path, *args: str) -> str:
    """Run ``git -C root <args>`` and return stdout, raising GitError on failure."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root(start: Path | None = None) -> Path:
    """Return the top-level directory of the git repository containing ``start``."""
    base = Path.cwd() if start is None else start
    return Path(git(base, "rev-parse", "--show-toplevel").strip())


def tracked_files(root: Path) -> list[str]:
    """Return every tracked path relative to ``root``."""
    out = git(root, "ls-files", "-z")
    return [p for p in out.split("\0") if p]


def first_commit(root: Path, path: str) -> str | None:
    """Return the SHA of the commit that first added ``path``, or None if never committed."""
    out = git(root, "log", "--format=%H", "--diff-filter=A", "--follow", "--", path)
    shas = out.split()
    return shas[-1] if shas else None


def commits_touching(root: Path, path: str, since: str) -> list[str]:
    """Return commits after ``since`` (exclusive) up to HEAD that changed ``path``."""
    return git(root, "log", "--format=%H", f"{since}..HEAD", "--", path).split()


def is_strict_ancestor(root: Path, older: str, newer: str) -> bool:
    """Return True if ``older`` is an ancestor of ``newer`` and they differ."""
    if git(root, "rev-parse", older).strip() == git(root, "rev-parse", newer).strip():
        return False
    proc = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
