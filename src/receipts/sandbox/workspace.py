"""Disposable workspaces: a fresh copy of a task repository with a known base commit.

:func:`create_workspace` copies a task repository into a new directory and returns its
path and base commit (the commit a run's diff is taken against):

- A source that is not a git repository is copied and committed once, with a fixed
  identity and date, so the same files always give the same base commit.
- A source that is a git repository keeps its history: it is cloned without
  ``--local`` (no hooks, no configuration, no shared object files), its working tree
  is then copied over the clone, and when that tree differs from ``HEAD`` it is
  committed, so the base commit is exactly the state the agent starts from. The
  ``origin`` remote is removed so nothing in the workspace can push to the source.

Every git command here runs on the host, outside any sandbox, so none of them may run
repository-controlled code: the system and global configuration are ignored, hooks
and fsmonitor are disabled, and the source's own ``.git`` directory (configuration,
hooks, filters) is never copied. ``HOME`` and ``XDG_CONFIG_HOME`` are ``/dev/null``,
so git's per-user files (``~/.config/git/ignore`` and ``attributes``) can never be
files of the repository itself. Repositories are made with an empty template, so the
workspace has no sample hooks either. Symlinks are copied as symlinks, never followed.
The workspace also gets the fixed identity as its local git user, so an agent can
commit inside the sandbox.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import NamedTuple

from receipts.sandbox.env import DEFAULT_PATH

IDENTITY_NAME = "receipts"
IDENTITY_EMAIL = "receipts@localhost"
FIXED_DATE = "2026-01-01T00:00:00Z"
BASE_MESSAGE = "receipts: workspace base"

#: Options for every host git command: no hooks, no fsmonitor, no signing, no CRLF.
GIT_OPTIONS: tuple[str, ...] = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "init.defaultBranch=main",
)

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class WorkspaceError(RuntimeError):
    """Raised when a git step of building a workspace fails."""


class Workspace(NamedTuple):
    """A workspace directory and the commit its run is diffed against."""

    path: Path
    base_commit: str


def git_env(home: str | Path = os.devnull) -> dict[str, str]:
    """The environment of host git commands: an allowlist with the fixed identity.

    ``home`` becomes both ``HOME`` and ``XDG_CONFIG_HOME``. The default,
    ``/dev/null``, can hold no files, so git finds no per-user ignore or attributes
    file (it treats the "Not a directory" error as a missing file).
    """
    return {
        "PATH": DEFAULT_PATH,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": IDENTITY_NAME,
        "GIT_AUTHOR_EMAIL": IDENTITY_EMAIL,
        "GIT_COMMITTER_NAME": IDENTITY_NAME,
        "GIT_COMMITTER_EMAIL": IDENTITY_EMAIL,
        "GIT_AUTHOR_DATE": FIXED_DATE,
        "GIT_COMMITTER_DATE": FIXED_DATE,
    }


def _git_executable() -> str:
    found = shutil.which("git")
    if found is None:
        raise WorkspaceError("git is not installed")
    return found


def _git(
    cwd: Path, *args: str, check: bool = True, options: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    argv = [_git_executable(), *GIT_OPTIONS, *options, "-C", str(cwd), *args]
    result = subprocess.run(
        argv, capture_output=True, text=True, check=False, env=git_env(), timeout=600
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        reason = detail[-1] if detail else f"exit code {result.returncode}"
        raise WorkspaceError(f"git {args[0]} failed: {reason}")
    return result


def is_git_repository(path: Path) -> bool:
    """True when ``path`` has its own ``.git`` entry (a directory or a gitlink file)."""
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def copy_tree(source: Path, dest: Path) -> None:
    """Copy ``source``'s contents into the existing ``dest``, except a top-level ``.git``.

    Symlinks are recreated as symlinks (their targets are never read), and file modes
    and times are kept.
    """
    for entry in sorted(source.iterdir()):
        if entry.name == ".git":
            continue
        target = dest / entry.name
        if entry.is_symlink():
            target.symlink_to(entry.readlink())
        elif entry.is_dir():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target)


def _commit_if_changed(path: Path) -> None:
    _git(path, "add", "--all")
    head = _git(path, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    if head.returncode == 0:
        diff = _git(path, "diff", "--cached", "--quiet", "HEAD", "--", check=False)
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            raise WorkspaceError(f"git diff failed: {diff.stderr.strip()}")
    _git(path, "commit", "--quiet", "--allow-empty", "--no-verify", "-m", BASE_MESSAGE)


def _workspace_prefix(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("-", name).strip("-.") or "workspace"
    return cleaned[:60] + "-"


def create_workspace(
    source_dir: str | Path, root: str | Path, *, name: str | None = None
) -> Workspace:
    """Copy ``source_dir`` into a fresh directory under ``root`` and commit its state.

    Args:
        source_dir: The task repository (a plain directory or a git repository).
        root: Where workspaces are created (made if missing). It may not be inside
            ``source_dir``.
        name: Prefix of the new directory's name; the source's name if None.

    Returns:
        The new workspace's resolved path and its base commit SHA.

    Raises:
        ValueError: ``source_dir`` is not a directory, or ``root`` is inside it.
        WorkspaceError: A git step failed (the partial workspace is removed).
    """
    source = Path(source_dir).resolve()
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    root_path = root_path.resolve()
    if root_path == source or source in root_path.parents:
        raise ValueError(f"workspace root {root_path} is inside the source {source}")
    path = Path(tempfile.mkdtemp(prefix=_workspace_prefix(name or source.name), dir=root_path))
    try:
        if is_git_repository(source):
            _git(
                root_path,
                "clone",
                "--quiet",
                "--no-local",
                "--no-checkout",
                "--template=",
                "--",
                str(source),
                str(path),
                options=("-c", f"safe.directory={source}"),
            )
            _git(path, "remote", "remove", "origin")
        else:
            _git(path, "init", "--quiet", "--template=")
        copy_tree(source, path)
        _git(path, "config", "user.name", IDENTITY_NAME)
        _git(path, "config", "user.email", IDENTITY_EMAIL)
        _git(path, "config", "commit.gpgsign", "false")
        _commit_if_changed(path)
        base = _git(path, "rev-parse", "HEAD").stdout.strip()
    except BaseException:
        remove_workspace(path, root_path)
        raise
    return Workspace(path=path, base_commit=base)


def make_tree_writable(root: Path) -> None:
    """Give the owner full access to every directory under ``root`` (symlinks untouched).

    A command may leave directories without write or search permission, which would
    stop :func:`shutil.rmtree` for a user other than root.
    """
    pending = [root]
    while pending:
        current = pending.pop()
        if current.is_symlink() or not current.is_dir():
            continue
        with suppress(OSError):
            current.chmod(current.stat().st_mode | stat.S_IRWXU)
        with suppress(OSError):
            pending.extend(current.iterdir())


def _rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except PermissionError:
        make_tree_writable(path)
        shutil.rmtree(path)


def remove_workspace(path: str | Path, root: str | Path) -> bool:
    """Delete the workspace ``path``, which must lie strictly inside ``root``.

    A symlink is removed as a link (its target is left alone), and directories a
    command made read-only are made writable first. Nothing outside ``root`` is ever
    deleted.

    Returns:
        True if something was deleted, False if ``path`` did not exist.

    Raises:
        ValueError: ``path`` (its parent directories resolved) is not strictly inside
            ``root``.
    """
    root_path = Path(root).resolve()
    given = Path(path)
    target = given.parent.resolve() / given.name
    if root_path not in target.parents:
        raise ValueError(f"refusing to delete {given}: it is not inside {root_path}")
    if target.is_symlink() or target.is_file():
        target.unlink()
        return True
    if not target.exists():
        return False
    _rmtree(target)
    return True


def remove_all_workspaces(root: str | Path) -> int:
    """Delete every directory directly under ``root``; return how many were deleted."""
    root_path = Path(root)
    if not root_path.is_dir():
        return 0
    removed = 0
    for child in sorted(root_path.iterdir()):
        if child.is_dir() and not child.is_symlink():
            removed += remove_workspace(child, root_path)
    return removed


@contextmanager
def temporary_workspace(
    source_dir: str | Path, root: str | Path | None = None, *, name: str | None = None
) -> Iterator[Workspace]:
    """Yield a workspace from :func:`create_workspace` and delete it afterwards.

    With ``root`` None, a private temporary root is created and deleted as well.
    """
    own_root = root is None
    if root is None:
        root_path = Path(tempfile.mkdtemp(prefix="receipts-workspaces-"))
    else:
        root_path = Path(root)
    workspace = create_workspace(source_dir, root_path, name=name)
    try:
        yield workspace
    finally:
        remove_workspace(workspace.path, root_path)
        if own_root:
            with suppress(OSError):
                root_path.rmdir()
