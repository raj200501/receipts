"""Tests for the machinery every backend shares (policy, cwd, rlimits, launcher, run)."""

from __future__ import annotations

import resource
import shutil
import subprocess
from pathlib import Path

import pytest

from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    LAUNCHER_ARG0,
    LIMITS_FAILED_EXIT_CODE,
    MAX_COMMAND_BYTES,
    CwdError,
    check_readonly_paths,
    check_workspace,
    command_problem,
    find_executable,
    launcher_script,
    resolve_cwd,
    rlimit_values,
    validate_policy,
)
from receipts.sandbox.local import LocalTestSandbox
from receipts.sandbox.process import CANNOT_RUN_EXIT_CODE

BASH = shutil.which("bash") or "/bin/bash"


def run_launcher(script: str, cmd: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [BASH, "-c", script, LAUNCHER_ARG0, cmd],
        capture_output=True,
        text=True,
        check=False,
        env=env if env is not None else {"PATH": "/usr/bin:/bin"},
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


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
