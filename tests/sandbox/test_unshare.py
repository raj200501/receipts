"""Tests for UnshareSandbox: network isolation only, writes NOT confined (D5)."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from receipts.sandbox.api import CommandOutcome, Sandbox, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import LAUNCHER_ARG0, MAX_COMMAND_BYTES, CwdError, rlimit_values
from receipts.sandbox.cgroup import pids_cgroup_parent
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.process import TIMEOUT_EXIT_CODE
from receipts.sandbox.unshare import UnshareSandbox, private_mounts, probe_unshare

from .helpers import (
    CONNECT_CMD,
    FORK_CMD,
    background_sleeper,
    requires,
    unique_marker,
    unshare_probe,
    wait_until_gone,
)

needs_unshare = requires(unshare_probe())


@pytest.fixture
def host_files() -> Iterator[list[Path]]:
    """Host files a test creates outside its temporary directory; removed afterwards."""
    paths: list[Path] = []
    yield paths
    for path in paths:
        path.unlink(missing_ok=True)


def test_private_mounts_cover_directories_and_bind_kept_paths_back(tmp_path: Path) -> None:
    covered = tmp_path / "covered"
    ws = covered / "a" / "ws"
    ws.mkdir(parents=True)
    tool = covered / "tool.sh"
    tool.write_text("synthetic", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    steps = private_mounts(
        [tool, ws, outside],
        mount="/bin/mount",
        mkdir="/bin/mkdir",
        private_dirs=[(str(covered), "1777"), (str(tmp_path / "absent"), "0755")],
    )
    # Shallower paths first, so a nested kept path is bound after its parent.
    assert steps[0] == f"exec {{_receipts_keep0}}<{tool}"
    assert steps[1] == f"exec {{_receipts_keep1}}<{ws}"
    assert steps[2] == f"/bin/mount -t tmpfs -o mode=1777,nosuid,nodev receipts-private {covered}"
    assert f": > {tool}" in steps[3] and '"/proc/self/fd/$_receipts_keep0"' in steps[3]
    assert steps[4].startswith(f"/bin/mkdir -p -- {ws} && /bin/mount --no-canonicalize --bind")
    assert steps[5] == (
        "exec {_receipts_keep0}<&- {_receipts_keep1}<&- && unset _receipts_keep0 _receipts_keep1"
    )
    assert len(steps) == 6
    assert private_mounts([outside], mount="m", mkdir="d", private_dirs=[]) == []


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
    probe = probe_unshare()
    assert probe.ok and "writes NOT confined" in probe.detail
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
def test_writes_are_not_confined(workspace: Path, host_files: list[Path]) -> None:
    outside = Path("/var/tmp") / f"receipts-unconfined-{uuid.uuid4().hex}"
    host_files.append(outside)
    assert UnshareSandbox(workspace).run(f"echo x > {outside}").exit_code == 0
    assert outside.read_text(encoding="utf-8") == "x\n"


@needs_unshare
def test_host_sockets_and_cgroups_are_out_of_reach(
    workspace: Path, tmp_path: Path, host_files: list[Path]
) -> None:
    beside = tmp_path / "beside-the-workspace.txt"
    beside.write_text("host", encoding="utf-8")
    in_run = Path("/run") / f"receipts-private-{uuid.uuid4().hex}"
    in_run.write_text("host", encoding="utf-8")
    host_files.append(in_run)
    private = Path("/tmp") / f"receipts-private-{uuid.uuid4().hex}.txt"
    host_files.append(private)
    box = UnshareSandbox(workspace)
    outcome = box.run(
        f"test -e {beside} && echo beside; test -e {in_run} && echo run; "
        f"ls -A /sys/fs/cgroup | wc -l; echo x > made.txt; echo y > {private}; pwd"
    )
    assert outcome.stdout.splitlines() == ["0", str(workspace.resolve())]
    assert (workspace / "made.txt").read_text(encoding="utf-8") == "x\n"
    assert not private.exists()


@needs_unshare
def test_readonly_paths_under_private_directories_stay_visible(
    workspace: Path, tmp_path: Path
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "note.txt").write_text("tool data\n", encoding="utf-8")
    single = tmp_path / "single.txt"
    single.write_text("one file\n", encoding="utf-8")
    box = UnshareSandbox(workspace, SandboxPolicy(readonly_paths=(tools, single)))
    outcome = box.run(f"cat {tools / 'note.txt'} {single}")
    assert (outcome.exit_code, outcome.stdout) == (0, "tool data\none file\n")


@needs_unshare
def test_readonly_paths_must_exist(workspace: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        UnshareSandbox(workspace, SandboxPolicy(readonly_paths=(tmp_path / "missing",)))
    tools = tmp_path / "tools"
    tools.mkdir()
    box = UnshareSandbox(workspace, SandboxPolicy(readonly_paths=(tools,)))
    shutil.rmtree(tools)
    with pytest.raises(SandboxUnavailableError, match="read-only paths no longer exist"):
        box.run("true")


@needs_unshare
def test_a_failed_setup_step_is_a_sandbox_failure(workspace: Path) -> None:
    box = UnshareSandbox(workspace)
    box._mount = shutil.which("false") or "/bin/false"
    with pytest.raises(SandboxUnavailableError, match="unshare: the sandbox setup failed"):
        box.run("echo never")


@needs_unshare
def test_max_procs_is_enforced(workspace: Path) -> None:
    box = UnshareSandbox(workspace, SandboxPolicy(max_procs=10, timeout_s=60))
    if box.process_limit == "none":
        pytest.skip("running as root without a writable pids cgroup: max_procs is not enforced")
    started, failed = map(int, box.run(FORK_CMD).stdout.split())
    assert started < 10 and failed > 50
    parent = pids_cgroup_parent()
    if box.process_limit == "cgroup" and parent is not None:
        # /sys/fs/cgroup is an empty tmpfs inside, so the parent's cgroup.procs is absent.
        escape = box.run(f"echo $$ > {parent / 'cgroup.procs'} && echo ESCAPED")
        assert "ESCAPED" not in escape.stdout


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


def failing_true(self: object, cmd: str, **kwargs: object) -> CommandOutcome:
    """A synthetic outcome for a sandbox that started ``true`` and saw it fail."""
    return CommandOutcome(
        cmd=cmd,
        cwd=".",
        exit_code=3,
        stdout="",
        stderr="synthetic: true failed\n",
        duration_s=0.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_sha256="",
        stderr_sha256="",
        backend="synthetic",
    )


@needs_unshare
def test_probe_reports_a_trivial_command_that_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UnshareSandbox, "run", failing_true)
    probe = probe_unshare()
    assert not probe.ok and probe.detail == "namespaces not permitted: synthetic: true failed"
