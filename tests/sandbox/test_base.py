"""Tests for the machinery every backend shares (policy, cwd, rlimits, launcher, run)."""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from receipts.sandbox import base as base_module
from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    LAUNCHER_ARG0,
    LIMITS_FAILED,
    LIMITS_FAILED_EXIT_CODE,
    MAX_COMMAND_BYTES,
    SETUP_FAILED,
    SETUP_FAILED_EXIT_CODE,
    STARTED,
    CwdError,
    ProcessSandbox,
    StartReport,
    StatusChannel,
    _high_fd,
    check_readonly_paths,
    check_workspace,
    command_problem,
    find_executable,
    launcher_script,
    require_paths,
    resolve_cwd,
    rlimit_values,
    validate_policy,
)
from receipts.sandbox.cgroup import pids_cgroup_parent
from receipts.sandbox.local import LocalTestSandbox
from receipts.sandbox.process import CANNOT_RUN_EXIT_CODE, TIMEOUT_EXIT_CODE, Launch

BASH = shutil.which("bash") or "/bin/bash"


def run_launcher(
    script: str,
    cmd: str,
    env: dict[str, str] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> tuple[int, str, str]:
    """Run a launcher script with plain bash (no sandbox): ``(exit code, stdout, stderr)``."""
    proc = subprocess.run(
        [BASH, "-c", script, LAUNCHER_ARG0, cmd],
        capture_output=True,
        text=True,
        check=False,
        env=env if env is not None else {"PATH": "/usr/bin:/bin"},
        timeout=30,
        pass_fds=pass_fds,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_with_status(script: str, cmd: str) -> tuple[int, str, str, str]:
    """Like :func:`run_launcher`, with a status pipe: ``(code, stdout, stderr, status)``."""
    with StatusChannel() as channel:
        code, out, err = run_launcher(script, cmd, pass_fds=(channel.write_fd,))
        return code, out, err, channel.read()


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_s": 0},
        {"timeout_s": -1.0},
        {"timeout_s": float("inf")},
        {"timeout_s": float("nan")},
        {"memory_mb": 0},
        {"cpu_s": -1},
        {"max_procs": 0},
        {"max_output_chars": 0},
        {"max_output_chars": 1},
        {"max_procs": True},
    ],
)
def test_validate_policy_refuses_non_positive_limits(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_policy(SandboxPolicy(**changes))  # type: ignore[arg-type]  # deliberately bad values


def test_validate_policy_accepts_the_defaults() -> None:
    validate_policy(SandboxPolicy())


def test_check_workspace_resolves_and_refuses_non_directories(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert check_workspace(tmp_path / "link") == (tmp_path / "real").resolve()
    with pytest.raises(ValueError, match="not a directory"):
        check_workspace(tmp_path / "missing")
    with pytest.raises(ValueError, match="root"):
        check_workspace("/")


def test_check_readonly_paths(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    paths = [tmp_path / "tools", tmp_path / "tools" / ".." / "tools"]
    assert check_readonly_paths(paths) == ((tmp_path / "tools").resolve(),)
    with pytest.raises(ValueError, match="does not exist"):
        check_readonly_paths([tmp_path / "missing"])


def test_resolve_cwd_normalizes_paths_inside_the_workspace(workspace: Path) -> None:
    ws = workspace.resolve()
    assert resolve_cwd(ws, ".") == (ws, ".")
    assert resolve_cwd(ws, "sub") == (ws / "sub", "sub")
    assert resolve_cwd(ws, "./sub/../sub/") == (ws / "sub", "sub")
    (ws / "inner").symlink_to(ws / "sub")
    assert resolve_cwd(ws, "inner") == (ws / "sub", "sub")


@pytest.mark.parametrize("cwd", ["/etc", "..", "sub/../..", "out", "missing", "file.txt", "a\0b"])
def test_resolve_cwd_rejects_escapes_and_non_directories(workspace: Path, cwd: str) -> None:
    ws = workspace.resolve()
    (ws / "out").symlink_to("/etc")
    (ws / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(CwdError):
        resolve_cwd(ws, cwd)


def test_find_executable() -> None:
    assert Path(find_executable("bash", "bash")).is_absolute()
    with pytest.raises(SandboxUnavailableError, match="no-such-tool"):
        find_executable("receipts-no-such-tool", "no-such-tool")


def test_rlimit_values_follow_the_policy() -> None:
    policy = SandboxPolicy(memory_mb=512, cpu_s=30, max_procs=64)
    limits = rlimit_values(policy)
    assert set(limits) == {"v", "t", "u"}
    assert limits["v"] <= 512 * 1024 and limits["t"] <= 30 and limits["u"] <= 64


def test_rlimit_values_never_exceed_current_hard_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    hard = {resource.RLIMIT_AS: 100 * 1024 * 1024, resource.RLIMIT_CPU: 7, resource.RLIMIT_NPROC: 9}
    monkeypatch.setattr(resource, "getrlimit", lambda which: (hard[which], hard[which]))
    assert rlimit_values(SandboxPolicy()) == {"v": 100 * 1024, "t": 7, "u": 9}


def test_rlimit_values_keep_the_policy_under_unlimited_hard_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unlimited = (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    monkeypatch.setattr(resource, "getrlimit", lambda which: unlimited)
    policy = SandboxPolicy(memory_mb=2048, cpu_s=60, max_procs=100)
    assert rlimit_values(policy) == {"v": 2048 * 1024, "t": 60, "u": 100}


def test_launcher_runs_the_command_with_bash_dash_c() -> None:
    script = launcher_script(BASH)
    assert run_launcher(script, 'echo "$0" out; echo err >&2; exit 5') == (5, "bash out\n", "err\n")
    assert run_launcher(script, "--version")[0] == 127


def test_launcher_applies_limits() -> None:
    script = launcher_script(BASH, {"v": 1048576, "t": 7, "u": 99})
    code, out, _ = run_launcher(script, "ulimit -v; ulimit -t; ulimit -u; ulimit -H -t")
    assert (code, out.split()) == (0, ["1048576", "7", "99", "7"])


def test_launcher_fails_closed_when_a_limit_is_refused() -> None:
    code, out, err = run_launcher(launcher_script(BASH, {"t": -5}), "echo ran")
    assert code == LIMITS_FAILED_EXIT_CODE and out == ""
    assert "ulimit" in err


def test_launcher_keeps_its_own_job_notices_out_of_stderr() -> None:
    code, _, err = run_launcher(launcher_script(BASH), "kill -9 $$")
    assert (code, err) == (137, "")


def test_launcher_unsets_variables_not_kept() -> None:
    script = launcher_script(BASH, keep=["PATH", "KEEP_ME"])
    env = {"PATH": "/usr/bin:/bin", "KEEP_ME": "1", "IMAGE_VAR": "2"}
    _, out, _ = run_launcher(script, "env", env)
    names = {line.split("=", 1)[0] for line in out.splitlines()}
    assert names == {"PATH", "KEEP_ME", "PWD", "SHLVL", "_"}


def test_launcher_refuses_bad_keep_names() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        launcher_script(BASH, keep=["OK", "BAD NAME"])
    with pytest.raises(ValueError, match="status_fd"):
        launcher_script(BASH, status_fd=-1)


def test_launcher_reports_the_start_and_closes_the_status_fd_first() -> None:
    with StatusChannel() as channel:
        fd = channel.write_fd
        script = launcher_script(BASH, {"t": 30}, status_fd=fd)
        code, out, err = run_launcher(
            script, f"echo forged >&{fd} || echo closed; echo ran", pass_fds=(fd,)
        )
        status = channel.read()
    assert status == f"{STARTED}\n"
    assert (code, out) == (0, "closed\nran\n")
    assert "Bad file descriptor" in err


def test_launcher_reports_refused_limits_on_the_status_fd() -> None:
    code, out, _, status = run_with_status(
        launcher_script(BASH, {"t": -5}, status_fd=99), "echo ran"
    )
    # fd 99 is not open here, so the report itself fails: the exit code still holds.
    assert (code, out) == (LIMITS_FAILED_EXIT_CODE, "") and status == ""
    with StatusChannel() as channel:
        script = launcher_script(BASH, {"t": -5}, status_fd=channel.write_fd)
        code, out, _ = run_launcher(script, "echo ran", pass_fds=(channel.write_fd,))
        assert (code, out, channel.read()) == (LIMITS_FAILED_EXIT_CODE, "", f"{LIMITS_FAILED}\n")


def test_launcher_runs_the_prologue_and_stops_when_a_step_fails() -> None:
    with StatusChannel() as channel:
        fd = channel.write_fd
        script = launcher_script(BASH, status_fd=fd, prologue=["true", "echo step >&2"])
        assert run_launcher(script, "echo ran", pass_fds=(fd,))[:2] == (0, "ran\n")
        assert channel.read() == f"{STARTED}\n"
    with StatusChannel() as channel:
        fd = channel.write_fd
        script = launcher_script(BASH, status_fd=fd, prologue=["false", "echo never"])
        code, out, _ = run_launcher(script, "echo ran", pass_fds=(fd,))
        assert (code, out, channel.read()) == (SETUP_FAILED_EXIT_CODE, "", f"{SETUP_FAILED}\n")
    code, out, _ = run_launcher(launcher_script(BASH, prologue=["false"]), "echo ran")
    assert (code, out) == (SETUP_FAILED_EXIT_CODE, "")


def test_launcher_can_report_on_stdout() -> None:
    code, out, _ = run_launcher(launcher_script(BASH, status_fd=1), "echo ran")
    assert (code, out) == (0, f"{STARTED}\nran\n")


def test_status_channel_ends_are_above_the_standard_streams() -> None:
    with StatusChannel() as channel:
        assert channel.write_fd > 2
        assert channel.read() == ""
        assert channel.write_fd == -1
    saved = os.dup(0)
    try:
        os.close(0)
        read_fd, write_fd = os.pipe()
        assert read_fd == 0
        moved = _high_fd(read_fd)
        assert moved > 2
        os.close(moved)
        os.close(write_fd)
    finally:
        os.dup2(saved, 0)
        os.close(saved)


def test_require_paths(tmp_path: Path) -> None:
    require_paths([tmp_path], "read-only paths")
    with pytest.raises(SandboxUnavailableError, match="read-only paths no longer exist"):
        require_paths([tmp_path, tmp_path / "gone"], "read-only paths")


def test_run_checks_its_arguments(workspace: Path) -> None:
    box = LocalTestSandbox(workspace, allow_unsandboxed_for_tests=True)
    with pytest.raises(ValueError, match="timeout_s"):
        box.run("true", timeout_s=0)
    with pytest.raises(CwdError):
        box.run("true", cwd="..")


def test_constructor_checks_policy_and_capture_limit(workspace: Path) -> None:
    with pytest.raises(ValueError, match="memory_mb"):
        LocalTestSandbox(workspace, SandboxPolicy(memory_mb=0), allow_unsandboxed_for_tests=True)
    with pytest.raises(ValueError, match="max_capture_bytes"):
        LocalTestSandbox(workspace, allow_unsandboxed_for_tests=True, max_capture_bytes=0)
    with pytest.raises(ValueError, match="GH_TOKEN"):
        LocalTestSandbox(
            workspace,
            SandboxPolicy(env={"GH_TOKEN": "synthetic"}),
            allow_unsandboxed_for_tests=True,
        )


def test_properties(workspace: Path) -> None:
    policy = SandboxPolicy(timeout_s=5.0)
    box = LocalTestSandbox(workspace, policy, allow_unsandboxed_for_tests=True)
    assert box.policy is policy
    assert box.workspace == workspace.resolve()
    env = box.env
    env["MUTATED"] = "1"
    assert "MUTATED" not in box.env


def test_command_problem() -> None:
    assert command_problem("echo ok") is None
    assert command_problem("x" * MAX_COMMAND_BYTES) is None
    assert "NUL" in (command_problem("a\0b") or "")
    assert "surrogate" in (command_problem("echo \ud800") or "")
    assert "Argument list too long" in (command_problem("x" * (MAX_COMMAND_BYTES + 1)) or "")
    # The limit counts UTF-8 bytes, not characters.
    wide = "\u00e9" * (MAX_COMMAND_BYTES // 2 + 1)
    assert len(wide) < MAX_COMMAND_BYTES
    assert f"{len(wide.encode())} bytes" in (command_problem(wide) or "")


@pytest.mark.parametrize(
    ("cmd", "stdin", "reason"),
    [
        ("echo a\0b", None, "NUL"),
        ("echo \ud800", None, "surrogate"),
        ("#" + "x" * MAX_COMMAND_BYTES, None, "Argument list too long"),
        ("cat", "bad \udc80 input", "standard input"),
    ],
)
def test_a_command_bash_cannot_receive_is_reported_as_not_run(
    workspace: Path, cmd: str, stdin: str | None, reason: str
) -> None:
    box = LocalTestSandbox(workspace, allow_unsandboxed_for_tests=True)
    outcome = box.run(cmd, cwd="sub", stdin=stdin)
    assert outcome.exit_code == CANNOT_RUN_EXIT_CODE
    assert outcome.stderr.startswith("receipts: the command was not run: ")
    assert reason in outcome.stderr
    assert (outcome.cmd, outcome.cwd, outcome.backend) == (cmd, "sub", "fake")
    assert (outcome.stdout, outcome.timed_out, outcome.duration_s) == ("", False, 0.0)


def test_the_longest_command_that_fits_runs(workspace: Path) -> None:
    box = LocalTestSandbox(workspace, allow_unsandboxed_for_tests=True)
    outcome = box.run("#" + "x" * (MAX_COMMAND_BYTES - 1))
    assert (outcome.exit_code, outcome.stderr) == (0, "")


class ScriptSandbox(ProcessSandbox):
    """A test backend with no isolation whose launcher reports like the real ones.

    ``mode`` picks the synthetic behaviour: ``"ok"`` runs the real launcher,
    ``"broken"`` fails like a sandbox that never starts the command, ``"slow"`` sleeps
    before starting it, ``"limits"`` asks for a limit the kernel refuses, and
    ``"setup"`` has a prologue step that fails (like a mount that cannot be made).
    """

    backend_name: ClassVar[str] = "fake"
    confines_writes: ClassVar[bool] = False
    start_report: ClassVar[StartReport] = "fd"

    def __init__(self, workspace: Path, mode: str = "ok", **kwargs: object) -> None:
        super().__init__(workspace, **kwargs)  # type: ignore[arg-type]  # forwards keyword options
        self.mode = mode

    def launch(
        self, cmd: str, cwd: Path, *, interactive: bool = False, status_fd: int | None = None
    ) -> Launch:
        """Plain bash running the launcher (or a synthetic failure) for ``cmd``."""
        fds = () if status_fd is None else (status_fd,)
        if self.mode == "broken":
            argv: tuple[str, ...] = (BASH, "-c", "echo 'synthetic: cannot set up' >&2; exit 1")
            return Launch(argv=argv, env=self._env, cwd=cwd, pass_fds=fds)
        limits = {"t": -5} if self.mode == "limits" else None
        prologue = {"slow": ["sleep 5"], "setup": ["false"]}.get(self.mode, [])
        script = launcher_script(BASH, limits, status_fd=status_fd, prologue=prologue)
        argv = (BASH, "-c", script, LAUNCHER_ARG0, cmd)
        return Launch(argv=argv, env=self._env, cwd=cwd, pass_fds=fds)


class StdoutScriptSandbox(ScriptSandbox):
    """:class:`ScriptSandbox` whose launcher reports on stdout, as Docker's does."""

    start_report: ClassVar[StartReport] = "stdout"

    def launch(
        self, cmd: str, cwd: Path, *, interactive: bool = False, status_fd: int | None = None
    ) -> Launch:
        """The launcher reporting on stdout, or a synthetic daemon error."""
        marker = f"{STARTED}\n".encode()
        if self.mode == "broken":
            argv: tuple[str, ...] = (BASH, "-c", "echo 'docker: synthetic error' >&2; exit 125")
        else:
            argv = (BASH, "-c", launcher_script(BASH, status_fd=1), LAUNCHER_ARG0, cmd)
        return Launch(argv=argv, env=self._env, cwd=cwd, stdout_marker=marker)


def test_a_started_command_gives_its_own_outcome(workspace: Path) -> None:
    outcome = ScriptSandbox(workspace).run("echo out; exit 125")
    assert (outcome.exit_code, outcome.stdout) == (125, "out\n")
    marked = StdoutScriptSandbox(workspace).run("echo out; exit 125")
    assert (marked.exit_code, marked.stdout) == (125, "out\n")


def test_a_sandbox_that_never_starts_the_command_raises(workspace: Path) -> None:
    with pytest.raises(SandboxUnavailableError) as caught:
        ScriptSandbox(workspace, "broken").run("true")
    message = str(caught.value)
    assert "did not start the command" in message
    assert "exit code 1: synthetic: cannot set up" in message
    with pytest.raises(SandboxUnavailableError, match="exit code 125: docker: synthetic error"):
        StdoutScriptSandbox(workspace, "broken").run("true")


def test_refused_limits_and_failed_setup_are_named(workspace: Path) -> None:
    with pytest.raises(SandboxUnavailableError, match="refused the sandbox's limits"):
        ScriptSandbox(workspace, "limits").run("true")
    with pytest.raises(SandboxUnavailableError, match="sandbox setup failed"):
        ScriptSandbox(workspace, "setup").run("true")


def test_a_timeout_before_the_start_is_still_a_timeout(workspace: Path) -> None:
    outcome = ScriptSandbox(workspace, "slow").run("true", timeout_s=0.3)
    assert outcome.timed_out and outcome.exit_code == TIMEOUT_EXIT_CODE


def test_process_limit(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert LocalTestSandbox(workspace, allow_unsandboxed_for_tests=True).process_limit == "none"

    class Limited(ScriptSandbox):
        uses_pids_cgroup: ClassVar[bool] = True

    monkeypatch.setattr(base_module, "pids_cgroup_parent", lambda: None)
    assert Limited(workspace).process_limit == ("none" if os.geteuid() == 0 else "rlimit")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert Limited(workspace).process_limit == "rlimit"
    monkeypatch.setattr(base_module, "pids_cgroup_parent", lambda: workspace)
    assert Limited(workspace).process_limit == "cgroup"


@pytest.mark.skipif(pids_cgroup_parent() is None, reason="no writable pids cgroup here")
def test_commands_run_in_their_own_pids_cgroup(workspace: Path) -> None:
    class Limited(ScriptSandbox):
        uses_pids_cgroup: ClassVar[bool] = True

    box = Limited(workspace, policy=SandboxPolicy(max_procs=7))
    assert box.process_limit == "cgroup"
    outcome = box.run(
        "grep -E ':pids:|^0::' /proc/self/cgroup; "
        'cat "/sys/fs/cgroup/pids$(grep :pids: /proc/self/cgroup | cut -d: -f3)/pids.max"'
    )
    assert outcome.exit_code == 0
    assert "/receipts-" in outcome.stdout and outcome.stdout.rstrip().endswith("7")
    parent = pids_cgroup_parent()
    assert parent is not None
    leftovers = [p.name for p in parent.iterdir() if p.name.startswith(f"receipts-{os.getpid()}-")]
    assert leftovers == []
