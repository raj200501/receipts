"""Tests for LocalTestSandbox (no isolation; these commands are this suite's own fixtures)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from receipts.sandbox.api import Sandbox, SandboxPolicy
from receipts.sandbox.base import CwdError
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.local import LocalTestSandbox
from receipts.sandbox.process import TIMEOUT_EXIT_CODE

from .helpers import background_sleeper, unique_marker, wait_until_gone


def local(workspace: Path, policy: SandboxPolicy | None = None, **kwargs: int) -> LocalTestSandbox:
    return LocalTestSandbox(workspace, policy, allow_unsandboxed_for_tests=True, **kwargs)


@pytest.mark.parametrize("flag", [False, 1, "yes"])
def test_constructor_requires_explicit_acknowledgement(workspace: Path, flag: object) -> None:
    with pytest.raises(ValueError, match="no isolation"):
        LocalTestSandbox(workspace, allow_unsandboxed_for_tests=flag)  # type: ignore[arg-type]  # deliberately not True


def test_it_is_a_sandbox_that_confines_nothing(workspace: Path) -> None:
    box = local(workspace)
    assert isinstance(box, Sandbox)
    assert box.backend == "fake"
    assert box.confines_writes is False


def test_run_reports_the_true_outcome(workspace: Path) -> None:
    outcome = local(workspace).run("echo out; echo err >&2; exit 3", cwd="sub")
    assert (outcome.exit_code, outcome.stdout, outcome.stderr) == (3, "out\n", "err\n")
    assert (outcome.cwd, outcome.backend, outcome.timed_out) == ("sub", "fake", False)
    assert outcome.stdout_sha256 == hashlib.sha256(b"out\n").hexdigest()


def test_commands_start_in_cwd_with_home_in_the_workspace(workspace: Path) -> None:
    outcome = local(workspace).run('pwd; echo "$HOME"; echo "$PATH"', cwd="sub")
    assert outcome.stdout.splitlines() == [
        str(workspace.resolve() / "sub"),
        str(workspace.resolve()),
        DEFAULT_PATH,
    ]


def test_host_secrets_are_absent(workspace: Path, planted_secrets: dict[str, str]) -> None:
    outcome = local(workspace).run("env")
    for name, value in planted_secrets.items():
        assert f"{name}=" not in outcome.stdout
        assert value not in outcome.stdout


def test_policy_env_reaches_the_command(workspace: Path) -> None:
    outcome = local(workspace, SandboxPolicy(env={"RECEIPTS_X": "42"})).run('echo "$RECEIPTS_X"')
    assert outcome.stdout == "42\n"


def test_stdin(workspace: Path) -> None:
    assert local(workspace).run("wc -l", stdin="a\nb\n").stdout.strip() == "2"


def test_a_dash_command_is_not_an_option(workspace: Path) -> None:
    outcome = local(workspace).run("--version")
    assert outcome.exit_code == 127


def test_timeout_kills_children(workspace: Path) -> None:
    marker = unique_marker()
    outcome = local(workspace).run(f"{background_sleeper(marker)} sleep 60", timeout_s=0.5)
    assert outcome.timed_out and outcome.exit_code == TIMEOUT_EXIT_CODE
    assert wait_until_gone(marker)


def test_policy_timeout_is_the_default(workspace: Path) -> None:
    outcome = local(workspace, SandboxPolicy(timeout_s=0.3)).run("sleep 30")
    assert outcome.timed_out and outcome.duration_s < 5


def test_output_is_capped(workspace: Path) -> None:
    box = local(workspace, SandboxPolicy(max_output_chars=1000))
    outcome = box.run("head -c 5000 /dev/zero | tr '\\0' a")
    assert outcome.stdout_truncated and len(outcome.stdout) < 1100
    assert outcome.stdout_sha256 == hashlib.sha256(b"a" * 5000).hexdigest()


def test_flooding_output_is_stopped(workspace: Path) -> None:
    outcome = local(workspace, max_capture_bytes=100_000).run("yes")
    assert outcome.exit_code == 137 and not outcome.timed_out
    assert "stopped because its stdout passed 100000 bytes" in outcome.stderr


def test_cwd_escape_is_rejected(workspace: Path) -> None:
    with pytest.raises(CwdError):
        local(workspace).run("pwd", cwd="../..")


def test_writes_are_not_confined(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    assert local(workspace).run(f"echo x > {outside}").exit_code == 0
    assert outside.read_text(encoding="utf-8") == "x\n"
