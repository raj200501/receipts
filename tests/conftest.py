"""Shared fixtures."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
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
def commit() -> Callable[[Path, str], str]:
    """Commit everything in a repository and return the new SHA."""

    def _commit(root: Path, message: str) -> str:
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "--allow-empty", "-m", message)
        return _git(root, "rev-parse", "HEAD").strip()

    return _commit
