"""Tests for UnshareSandbox: network isolation only, writes NOT confined (D5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from receipts.sandbox.api import Sandbox, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import LAUNCHER_ARG0, MAX_COMMAND_BYTES, CwdError, rlimit_values
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.process import TIMEOUT_EXIT_CODE
from receipts.sandbox.unshare import UnshareSandbox, probe_unshare

from .helpers import (
    CONNECT_CMD,
    background_sleeper,
    requires,
    unique_marker,
    unshare_probe,
    wait_until_gone,
)

needs_unshare = requires(unshare_probe())


def test_missing_unshare_is_unavailable(workspace: Path) -> None:
    with pytest.raises(SandboxUnavailableError, match="unshare"):
        UnshareSandbox(workspace, unshare="receipts-no-such-unshare")
    probe = probe_unshare("receipts-no-such-unshare")
    assert not probe.ok and "unshare" in probe.detail


@needs_unshare
def test_command_line(workspace: Path) -> None:
    box = UnshareSandbox(workspace)
    argv = box.launch("echo hi", workspace.resolve()).argv
    assert argv[1:6] == ("-rn", "--pid", "--fork", "--kill-child", "--mount-proc")
    assert argv[-2:] == (LAUNCHER_ARG0, "echo hi")
    networked = UnshareSandbox(workspace, SandboxPolicy(network=True))
    assert networked.launch("true", workspace.resolve()).argv[1] == "-r"


@needs_unshare
def test_probe_and_protocol(workspace: Path) -> None:
    assert probe_unshare().ok
    box = UnshareSandbox(workspace)
    assert isinstance(box, Sandbox)
    assert (box.backend, box.confines_writes) == ("unshare", False)
    assert Path(box.executable).is_absolute()


@needs_unshare
def test_network_is_unreachable(workspace: Path) -> None:
    outcome = UnshareSandbox(workspace).run(CONNECT_CMD)
    assert outcome.exit_code != 0
    assert "unreachable" in outcome.stderr.lower()


@needs_unshare
def test_host_secrets_are_absent(workspace: Path, planted_secrets: dict[str, str]) -> None:
    outcome = UnshareSandbox(workspace).run("env; cat /proc/self/environ")
    for name, value in planted_secrets.items():
        assert f"{name}=" not in outcome.stdout
        assert value not in outcome.stdout


@needs_unshare
def test_environment_and_cwd(workspace: Path) -> None:
    outcome = UnshareSandbox(workspace).run('pwd; echo "$HOME"; echo "$PATH"', cwd="sub")
    assert outcome.stdout.splitlines() == [
        str(workspace.resolve() / "sub"),
        str(workspace.resolve()),
        DEFAULT_PATH,
    ]


@needs_unshare
def test_proc_matches_the_pid_namespace(workspace: Path) -> None:
    script = "import os; print(open(f'/proc/{os.getpid()}/comm').read().strip())"
    assert UnshareSandbox(workspace).run(f'python3 -c "{script}"').stdout == "python3\n"


@needs_unshare
def test_writes_are_not_confined(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    assert UnshareSandbox(workspace).run(f"echo x > {outside}").exit_code == 0
    assert outside.read_text(encoding="utf-8") == "x\n"


@needs_unshare
@pytest.mark.parametrize("own_session", [False, True])
def test_timeout_kills_every_child(workspace: Path, own_session: bool) -> None:
    marker = unique_marker()
    cmd = f"{background_sleeper(marker, own_session=own_session)} sleep 60"
    outcome = UnshareSandbox(workspace).run(cmd, timeout_s=0.7)
    assert outcome.timed_out and outcome.exit_code == TIMEOUT_EXIT_CODE
    assert wait_until_gone(marker)


@needs_unshare
def test_background_processes_die_with_the_command(workspace: Path) -> None:
    marker = unique_marker()
    outcome = UnshareSandbox(workspace).run(f"{background_sleeper(marker, own_session=True)} true")
    assert outcome.exit_code == 0
    assert wait_until_gone(marker)


@needs_unshare
def test_rlimits_signals_caps_and_cwd(workspace: Path) -> None:
    policy = SandboxPolicy(memory_mb=300, cpu_s=50, max_procs=40, max_output_chars=100)
    box = UnshareSandbox(workspace, policy)
    limits = rlimit_values(policy)
    expected = [str(limits["v"]), str(limits["t"]), str(limits["u"])]
    assert box.run("ulimit -v; ulimit -t; ulimit -u").stdout.split() == expected
    killed = box.run("kill -9 $$")
    assert (killed.exit_code, killed.stderr) == (137, "")
    assert box.run("seq 1 1000").stdout_truncated
    assert box.run("cat", stdin="in").stdout == "in"
    assert box.run("#" + "x" * (MAX_COMMAND_BYTES - 1)).exit_code == 0
    with pytest.raises(CwdError):
        box.run("pwd", cwd="..")


def test_probe_reports_failing_namespaces(tmp_path: Path) -> None:
    fake = tmp_path / "unshare"
    fake.write_text("#!/bin/sh\necho 'unshare: synthetic EPERM' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    probe = probe_unshare(str(fake))
    assert not probe.ok and "synthetic EPERM" in probe.detail
    silent = tmp_path / "silent-unshare"
    silent.write_text("#!/bin/sh\nexit 4\n", encoding="utf-8")
    silent.chmod(0o755)
    assert "exit code 4" in probe_unshare(str(silent)).detail
