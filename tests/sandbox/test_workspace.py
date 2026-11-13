"""Tests for creating and removing workspaces (all task repositories here are synthetic)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from receipts.sandbox import workspace as ws_module
from receipts.sandbox.workspace import (
    BASE_MESSAGE,
    FIXED_DATE,
    IDENTITY_EMAIL,
    IDENTITY_NAME,
    Workspace,
    WorkspaceError,
    create_workspace,
    git_env,
    is_git_repository,
    make_tree_writable,
    remove_all_workspaces,
    remove_workspace,
    temporary_workspace,
)


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with the workspace module's host environment; return stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=git_env(repo),
    ).stdout.strip()


def make_task(src: Path) -> Path:
    """Write a plain (non-git) synthetic task repository at ``src``."""
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (src / "run.sh").write_text("#!/bin/sh\necho run\n", encoding="utf-8")
    (src / "run.sh").chmod(0o755)
    (src / "outside-link").symlink_to("/etc/hostname")
    return src


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """A plain synthetic task repository of this test's own."""
    return make_task(tmp_path / "task")


@pytest.fixture(scope="module")
def shared_task(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Workspace, Workspace]:
    """One synthetic task and two workspaces made from it (shared, never modified)."""
    base = tmp_path_factory.mktemp("shared")
    src = make_task(base / "task")
    return src, create_workspace(src, base / "root"), create_workspace(src, base / "root")


def test_plain_directory_is_copied_and_committed(
    shared_task: tuple[Path, Workspace, Workspace],
) -> None:
    src, ws, _ = shared_task
    assert isinstance(ws, Workspace)
    path, base = ws
    assert path.parent == (src.parent / "root").resolve()
    assert path.name.startswith("task-")
    assert (path / "pkg" / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"
    assert (path / "run.sh").stat().st_mode & stat.S_IXUSR
    assert (path / "outside-link").is_symlink()
    assert str((path / "outside-link").readlink()) == "/etc/hostname"
    assert git(path, "rev-parse", "HEAD") == base
    assert git(path, "status", "--porcelain") == ""
    assert git(path, "log", "--format=%an <%ae>|%cn <%ce>|%s") == (
        f"{IDENTITY_NAME} <{IDENTITY_EMAIL}>|{IDENTITY_NAME} <{IDENTITY_EMAIL}>|{BASE_MESSAGE}"
    )
    # newer git prints a UTC offset as "Z" for %aI, older git as "+00:00"
    assert git(path, "log", "--format=%aI") in {FIXED_DATE, FIXED_DATE.replace("Z", "+00:00")}
    assert git(path, "config", "user.email") == IDENTITY_EMAIL


def test_same_files_give_the_same_base_commit(
    shared_task: tuple[Path, Workspace, Workspace], tmp_path: Path
) -> None:
    src, first, second = shared_task
    assert first.path != second.path
    assert first.base_commit == second.base_commit
    changed = tmp_path / "changed"
    shutil.copytree(src, changed, symlinks=True)
    (changed / "pkg" / "mod.py").write_text("changed\n", encoding="utf-8")
    other = create_workspace(changed, tmp_path / "root", name="my task/1")
    assert other.base_commit != first.base_commit
    assert other.path.name.startswith("my-task-1-")


def test_workspace_prefix_is_sanitized() -> None:
    assert ws_module._workspace_prefix("my task/1") == "my-task-1-"
    assert ws_module._workspace_prefix("///") == "workspace-"
    assert len(ws_module._workspace_prefix("x" * 200)) == 61


def test_bad_arguments_are_refused(task_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a directory"):
        create_workspace(tmp_path / "missing", tmp_path / "root")
    with pytest.raises(ValueError, match="inside the source"):
        create_workspace(task_dir, task_dir / "nested")
    with pytest.raises(ValueError, match="inside the source"):
        create_workspace(task_dir, task_dir)


@pytest.fixture(scope="module")
def pristine_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A synthetic git repository with two commits (shared; tests copy it)."""
    base = tmp_path_factory.mktemp("pristine")
    src = make_task(base / "repo")
    git(src, "init", "--quiet", "--template=", "--initial-branch=main")
    for message in ("first", "second"):
        if message == "second":
            (src / "pkg" / "mod.py").write_text("def f():\n    return 2\n", encoding="utf-8")
        git(src, "add", "--all")
        git(
            src, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-qm", message
        )
    return src, git(src, "rev-parse", "HEAD")


@pytest.fixture
def repo(pristine_repo: tuple[Path, str], tmp_path: Path) -> tuple[Path, str]:
    """This test's own copy of the pristine repository; returns (path, HEAD)."""
    src, head = pristine_repo
    copy = tmp_path / "repo"
    shutil.copytree(src, copy, symlinks=True)
    return copy, head


def test_clean_repository_keeps_its_history_and_head(
    repo: tuple[Path, str], tmp_path: Path
) -> None:
    source, head = repo
    ws = create_workspace(source, tmp_path / "root")
    assert ws.base_commit == head
    assert git(ws.path, "rev-list", "--count", "HEAD") == "2"
    assert git(ws.path, "status", "--porcelain") == ""
    assert git(ws.path, "remote") == ""
    assert (ws.path / "pkg" / "mod.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"


def test_dirty_repository_state_becomes_the_base(repo: tuple[Path, str], tmp_path: Path) -> None:
    source, head = repo
    (source / "pkg" / "mod.py").write_text("uncommitted\n", encoding="utf-8")
    (source / "new.txt").write_text("untracked\n", encoding="utf-8")
    (source / "run.sh").unlink()
    ws = create_workspace(source, tmp_path / "root")
    assert ws.base_commit != head
    assert git(ws.path, "rev-parse", "HEAD^") == head
    assert git(ws.path, "status", "--porcelain") == ""
    assert sorted(git(ws.path, "ls-files").splitlines()) == [
        "new.txt",
        "outside-link",
        "pkg/mod.py",
    ]


def make_ignored_repo(src: Path) -> str:
    """A synthetic repository tracking files its own ``.gitignore`` matches; returns HEAD."""
    (src / "build").mkdir(parents=True)
    (src / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    (src / "app.py").write_text("x = 1\n", encoding="utf-8")
    (src / "fixtures.log").write_text("synthetic fixture\n", encoding="utf-8")
    (src / "build" / "vendored.js").write_text("// synthetic\n", encoding="utf-8")
    git(src, "init", "--quiet", "--template=")
    git(src, "add", ".gitignore", "app.py")
    git(src, "add", "--force", "fixtures.log", "build/vendored.js")
    git(src, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-qm", "m")
    return git(src, "rev-parse", "HEAD")


def test_tracked_files_that_match_gitignore_stay_tracked(tmp_path: Path) -> None:
    src = tmp_path / "src"
    head = make_ignored_repo(src)
    ws = create_workspace(src, tmp_path / "root")
    assert ws.base_commit == head
    assert sorted(git(ws.path, "ls-files").splitlines()) == [
        ".gitignore",
        "app.py",
        "build/vendored.js",
        "fixtures.log",
    ]
    assert git(ws.path, "status", "--porcelain") == ""


def test_edits_to_tracked_ignored_files_reach_the_base_commit(tmp_path: Path) -> None:
    src = tmp_path / "src"
    head = make_ignored_repo(src)
    (src / "fixtures.log").write_text("edited before the run\n", encoding="utf-8")
    (src / "new.log").write_text("untracked and ignored\n", encoding="utf-8")
    ws = create_workspace(src, tmp_path / "root")
    assert git(ws.path, "rev-parse", "HEAD^") == head
    assert git(ws.path, "diff", "--name-status", head, ws.base_commit) == "M\tfixtures.log"
    assert "new.log" not in git(ws.path, "ls-files").splitlines()


def test_empty_repository_gets_a_base_commit(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "--quiet", "--template=")
    (empty / "a.txt").write_text("a\n", encoding="utf-8")
    ws = create_workspace(empty, tmp_path / "root")
    assert git(ws.path, "ls-files") == "a.txt"
    assert git(ws.path, "rev-parse", "HEAD") == ws.base_commit


def test_source_hooks_filters_and_config_never_run_on_the_host(
    repo: tuple[Path, str], tmp_path: Path
) -> None:
    source, _ = repo
    tripwire = tmp_path / "tripwire"
    hook = source / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\ntouch {tripwire}-hook\n", encoding="utf-8")
    hook.chmod(0o755)
    git(source, "config", "filter.synthetic.clean", f"touch {tripwire}-filter; cat")
    git(source, "config", "core.fsmonitor", f"touch {tripwire}-fsmonitor")
    git(source, "config", "receipts.synthetic", "1")
    (source / ".gitattributes").write_text("* filter=synthetic\n", encoding="utf-8")
    (source / "dirty.txt").write_text("forces a commit\n", encoding="utf-8")
    ws = create_workspace(source, tmp_path / "root")
    assert sorted(tmp_path.glob("tripwire*")) == []
    assert not (ws.path / ".git" / "hooks" / "pre-commit").exists()
    config = (ws.path / ".git" / "config").read_text(encoding="utf-8")
    assert "synthetic" not in config and "fsmonitor" not in config


@pytest.mark.parametrize("as_git", [False, True])
def test_files_in_the_source_never_configure_the_host_git(
    task_dir: Path, tmp_path: Path, as_git: bool
) -> None:
    # Synthetic per-user git files inside the task repository: if host git commands
    # used the workspace as HOME, these would hide every .py file from the base commit.
    for name in ("ignore", "attributes"):
        target = task_dir / ".config" / "git" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("*.py\n" if name == "ignore" else "*.py -text\n", encoding="utf-8")
    (task_dir / ".gitconfig").write_text("[user]\n\tname = synthetic\n", encoding="utf-8")
    if as_git:
        git(task_dir, "init", "--quiet", "--template=")
    ws = create_workspace(task_dir, tmp_path / "root")
    tracked = git(ws.path, "ls-files").splitlines()
    assert "pkg/mod.py" in tracked and ".config/git/ignore" in tracked
    assert git(ws.path, "log", "--format=%an") == IDENTITY_NAME
    status = ws_module._git(ws.path, "status", "--porcelain")
    assert (status.stdout, status.stderr) == ("", "")


def test_git_env_home_is_outside_every_repository() -> None:
    env = git_env()
    assert env["HOME"] == env["XDG_CONFIG_HOME"] == os.devnull


def test_a_failed_step_leaves_nothing_behind(
    task_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ws_module._git

    def failing(cwd: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[0] == "commit":
            raise WorkspaceError("git commit failed: synthetic")
        return real(cwd, *args, **kwargs)  # type: ignore[arg-type]  # forwards keyword options

    monkeypatch.setattr(ws_module, "_git", failing)
    root = tmp_path / "root"
    with pytest.raises(WorkspaceError, match="synthetic"):
        create_workspace(task_dir, root)
    assert list(root.iterdir()) == []


def test_a_failing_diff_is_reported(
    task_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ws_module._git

    def broken_diff(cwd: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[0] == "diff":
            return subprocess.CompletedProcess(list(args), 128, "", "fatal: synthetic")
        return real(cwd, *args, **kwargs)  # type: ignore[arg-type]  # forwards keyword options

    source = tmp_path / "src"
    shutil.copytree(task_dir, source, symlinks=True)
    git(source, "init", "--quiet", "--template=")
    git(source, "add", "--all")
    git(source, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-qm", "m")
    monkeypatch.setattr(ws_module, "_git", broken_diff)
    with pytest.raises(WorkspaceError, match="git diff failed"):
        create_workspace(source, tmp_path / "root")


def test_git_errors_are_reported(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="git rev-parse failed"):
        ws_module._git(tmp_path, "rev-parse", "HEAD")


def test_missing_git_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("receipts.sandbox.workspace.shutil.which", lambda name: None)
    with pytest.raises(WorkspaceError, match="not installed"):
        ws_module._git(tmp_path, "status")


def test_git_env_is_an_allowlist(planted_secrets: dict[str, str], tmp_path: Path) -> None:
    env = git_env(tmp_path)
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_CONFIG_NOSYSTEM"] == "1"
    for name in planted_secrets:
        assert name not in env


def test_is_git_repository(tmp_path: Path) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert is_git_repository(tmp_path / "repo")
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    assert is_git_repository(tmp_path / "linked")
    assert not is_git_repository(tmp_path)


def test_remove_workspace(task_dir: Path, tmp_path: Path) -> None:
    root = tmp_path / "root"
    path = root / "ws"
    shutil.copytree(task_dir, path, symlinks=True)
    assert remove_workspace(path, root) is True
    assert not path.exists()
    assert remove_workspace(path, root) is False


def test_remove_workspace_never_leaves_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()
    for target in (keep, root, tmp_path):
        with pytest.raises(ValueError, match="not inside"):
            remove_workspace(target, root)
    (root / "link").symlink_to(keep)
    assert remove_workspace(root / "link", root) is True
    assert keep.is_dir() and not (root / "link").exists()
    (root / "file.txt").write_text("x", encoding="utf-8")
    assert remove_workspace(root / "file.txt", root) is True


@pytest.mark.parametrize("tail", ["..", "../.."])
def test_remove_workspace_refuses_a_path_naming_a_parent(tmp_path: Path, tail: str) -> None:
    root = tmp_path / "root"
    for name in ("ws-a", "ws-b", "other-run"):
        (root / name).mkdir(parents=True)
    with pytest.raises(ValueError, match="names no workspace"):
        remove_workspace(root / "ws-a" / tail, root)
    with pytest.raises(ValueError, match="names no workspace"):
        remove_workspace(f"{root}/ws-a/{tail}", root)
    with pytest.raises(ValueError):
        remove_workspace(".", root)
    assert sorted(p.name for p in root.iterdir()) == ["other-run", "ws-a", "ws-b"]


@pytest.mark.parametrize("spelling", ["{root}/ws-a/", "{root}/ws-a/.", "{root}/./ws-a"])
def test_remove_workspace_accepts_other_spellings_of_one_workspace(
    tmp_path: Path, spelling: str
) -> None:
    root = tmp_path / "root"
    for name in ("ws-a", "ws-b"):
        (root / name).mkdir(parents=True)
    assert remove_workspace(spelling.format(root=root), root) is True
    assert [p.name for p in root.iterdir()] == ["ws-b"]


def test_make_tree_writable(tmp_path: Path) -> None:
    locked = tmp_path / "a" / "b"
    locked.mkdir(parents=True)
    (tmp_path / "a" / "link").symlink_to("/etc")
    locked.chmod(0o500)
    (tmp_path / "a").chmod(0o500)
    make_tree_writable(tmp_path / "a")
    assert (tmp_path / "a").stat().st_mode & stat.S_IRWXU == stat.S_IRWXU
    assert locked.stat().st_mode & stat.S_IRWXU == stat.S_IRWXU


def test_rmtree_retries_after_a_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "root" / "ws"
    target.mkdir(parents=True)
    real = shutil.rmtree
    calls: list[Path] = []

    def flaky(path: Path, *args: object, **kwargs: object) -> None:
        calls.append(Path(path))
        if len(calls) == 1:
            raise PermissionError("synthetic")
        real(path)

    monkeypatch.setattr("receipts.sandbox.workspace.shutil.rmtree", flaky)
    assert remove_workspace(target, tmp_path / "root")
    assert len(calls) == 2 and not target.exists()


def test_remove_all_workspaces(task_dir: Path, tmp_path: Path) -> None:
    root = tmp_path / "root"
    for i in range(3):
        shutil.copytree(task_dir, root / f"ws-{i}", symlinks=True)
    (root / "note.txt").write_text("kept", encoding="utf-8")
    (root / "link").symlink_to(task_dir)
    assert remove_all_workspaces(root) == 3
    assert sorted(p.name for p in root.iterdir()) == ["link", "note.txt"]
    assert task_dir.is_dir()
    assert remove_all_workspaces(tmp_path / "missing") == 0


def test_temporary_workspace_removes_its_root_when_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[Path] = []
    real = tempfile.mkdtemp

    def recording(prefix: str | None = None) -> str:
        path = real(prefix=prefix)
        made.append(Path(path))
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", recording)
    with (
        pytest.raises(ValueError, match="not a directory"),
        temporary_workspace(tmp_path / "missing-source"),
    ):
        pass
    assert len(made) == 1 and not made[0].exists()


def test_temporary_workspace_with_and_without_a_root(task_dir: Path, tmp_path: Path) -> None:
    with temporary_workspace(task_dir) as ws:
        own_root = ws.path.parent
        assert (ws.path / "run.sh").exists()
    assert not own_root.exists()
    root = tmp_path / "root"
    with temporary_workspace(task_dir, root, name="t") as ws:
        assert ws.path.name.startswith("t-")
    assert root.is_dir() and list(root.iterdir()) == []
