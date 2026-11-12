"""Shared fixtures."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """An empty git repository with a local identity."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    return root


@pytest.fixture
def outside_tmp() -> Iterator[Path]:
    """A fresh directory under ``/var/tmp``, removed afterwards.

    Every bubblewrap sandbox replaces ``/tmp`` with a private tmpfs, so a checkout under
    ``tmp_path`` would look hidden even when the sandbox does not hide it. A test that
    checks what the sandbox itself hides builds its files here instead.
    """
    base = Path("/var/tmp")
    if not base.is_dir() or not os.access(base, os.W_OK):
        pytest.skip("/var/tmp is not a writable directory here")
    path = Path(tempfile.mkdtemp(prefix="receipts-test-", dir=base))
    try:
        yield path.resolve()
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def make_checkout() -> Callable[[Path], Path]:
    """Build a SYNTHETIC receipts checkout at a given directory and return it: the files
    that mark a checkout, a hidden check, a reference solution, and ``private/``."""

    def _make(root: Path) -> Path:
        (root / "src" / "receipts").mkdir(parents=True)
        (root / "pyproject.toml").write_text("[project]\nname = 'synthetic'\n", encoding="utf-8")
        task = root / "bench" / "tasks" / "py-synthetic"
        for part, name in (("hidden", "check.py"), ("reference", "solution.py")):
            (task / part).mkdir(parents=True)
            (task / part / name).write_text(f"# SYNTHETIC {part} file\n", encoding="utf-8")
        (root / "private").mkdir()
        (root / "private" / "notes.txt").write_text("SYNTHETIC private notes\n", "utf-8")
        return root

    return _make


@pytest.fixture
def commit() -> Callable[[Path, str], str]:
    """Commit everything in a repository and return the new SHA."""

    def _commit(root: Path, message: str) -> str:
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "--allow-empty", "-m", message)
        return _git(root, "rev-parse", "HEAD").strip()

    return _commit
