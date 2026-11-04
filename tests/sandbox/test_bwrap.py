"""Tests for BwrapSandbox: command-line layout (always) and real isolation (bwrap only)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from receipts.sandbox import bwrap as bwrap_module
from receipts.sandbox.api import Sandbox, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import LAUNCHER_ARG0, MAX_COMMAND_BYTES, CwdError, rlimit_values
from receipts.sandbox.bwrap import (
    SYSTEM_CREDENTIAL_PATHS,
    BwrapSandbox,
    default_hidden_paths,
    mount_args,
    probe_bwrap,
    project_root,
)
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.process import TIMEOUT_EXIT_CODE

from .helpers import (
    CONNECT_CMD,
    background_sleeper,
    bwrap_probe,
    requires,
    unique_marker,
    wait_until_gone,
)

needs_bwrap = requires(bwrap_probe())


@pytest.fixture
def host_paths() -> Iterator[list[Path]]:
    """Host paths a test expects the sandbox never to create; removed if one appears."""
    paths: list[Path] = []
    yield paths
    for path in paths:
        path.unlink(missing_ok=True)


def pairs(args: list[str]) -> list[tuple[str, str]]:
    """(option, destination) for each mount option, in order."""
    out = []
    i = 0
    while i < len(args):
        if args[i] in ("--tmpfs", "--dev", "--proc"):
            out.append((args[i], args[i + 1]))
            i += 2
        else:
            out.append((args[i], args[i + 2]))
            i += 3
    return out


# Layout (no bubblewrap needed) ------------------------------------------------------


def test_mount_order_puts_nested_mounts_after_their_parents(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    tools = tmp_path / "tools"
    secret = ws / "secret"
    token = ws / "token.txt"
    for d in (ws, tools, secret):
        d.mkdir(parents=True)
    token.write_text("synthetic", encoding="utf-8")
    order = pairs(mount_args(ws, [tools], [secret, token]))
    assert order[:3] == [("--ro-bind", "/"), ("--dev", "/dev"), ("--proc", "/proc")]
    dests = [dest for _, dest in order]
    assert dests.index("/tmp") < dests.index(str(ws)) < dests.index(str(secret))
    assert dests.index("/tmp") < dests.index(str(tools))
    assert ("--tmpfs", str(secret)) in order
    assert ("--ro-bind", str(token)) in order
    assert ("--bind", str(ws)) in order
    assert ("--ro-bind", str(tools)) in order


def test_a_mask_on_the_workspace_itself_loses_to_the_workspace(tmp_path: Path) -> None:
    order = pairs(mount_args(tmp_path, [], [tmp_path]))
    assert order.index(("--tmpfs", str(tmp_path))) < order.index(("--bind", str(tmp_path)))


def test_default_hidden_paths_find_credentials_and_the_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".config" / "gh").mkdir(parents=True)
    (home / ".netrc").write_text("synthetic", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    hidden = default_hidden_paths([home, home], project)
    assert (home / ".ssh").resolve() in hidden
    assert (home / ".config" / "gh").resolve() in hidden
    assert (home / ".netrc").resolve() in hidden
    assert project.resolve() in hidden
    assert (home / ".aws") not in hidden
    assert len(hidden) == len(set(hidden))


def test_system_credential_locations_are_hidden_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert {"/etc/shadow", "/etc/ssh", "/etc/ssl/private"} <= set(SYSTEM_CREDENTIAL_PATHS)
    present = tmp_path / "ssh"
    present.mkdir()
    absent = tmp_path / "missing"
    monkeypatch.setattr(bwrap_module, "SYSTEM_CREDENTIAL_PATHS", (str(present), str(absent)))
    hidden = default_hidden_paths([], tmp_path / "no-project")
    assert hidden == (present.resolve(),)


def test_project_root_is_this_checkout() -> None:
    root = project_root()
    assert root is not None and (root / "src" / "receipts" / "sandbox").is_dir()


def test_default_hidden_paths_include_the_checkout() -> None:
    root = project_root()
    assert root is not None and root in default_hidden_paths()


def test_missing_bwrap_is_unavailable(workspace: Path) -> None:
    with pytest.raises(SandboxUnavailableError, match="bubblewrap"):
        BwrapSandbox(workspace, bwrap="receipts-no-such-bwrap")
    probe = probe_bwrap("receipts-no-such-bwrap")
    assert not probe.ok and "bubblewrap" in probe.detail


def test_missing_readonly_path_is_refused(workspace: Path, tmp_path: Path) -> None:
    if not bwrap_probe().ok:
        pytest.skip("bubblewrap is not installed")
    with pytest.raises(ValueError, match="does not exist"):
        BwrapSandbox(workspace, SandboxPolicy(readonly_paths=(tmp_path / "missing",)))


@needs_bwrap
def test_command_line_isolates_and_rebuilds_the_environment(workspace: Path) -> None:
    box = BwrapSandbox(workspace, hide_paths=())
    argv = list(box.launch("echo hi", workspace.resolve()).argv)
    for flag in ("--unshare-all", "--die-with-parent", "--new-session", "--clearenv"):
        assert flag in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "--share-net" not in argv
    at = argv.index("PATH")
    assert argv[at - 1 : at + 2] == ["--setenv", "PATH", DEFAULT_PATH]
    assert argv[-4:-2] == ["-c", argv[-3]] and argv[-2:] == [LAUNCHER_ARG0, "echo hi"]
    limits = rlimit_values(box.policy)
    assert f"ulimit -S -H -v {limits['v']}" in argv[-3]
    networked = BwrapSandbox(workspace, SandboxPolicy(network=True), hide_paths=())
    assert "--share-net" in networked.launch("true", workspace.resolve()).argv


# Real isolation ---------------------------------------------------------------------


@needs_bwrap
def test_probe_and_protocol(workspace: Path) -> None:
    assert probe_bwrap().ok
    box = BwrapSandbox(workspace)
    assert isinstance(box, Sandbox)
    assert (box.backend, box.confines_writes) == ("bwrap", True)
    assert Path(box.executable).is_absolute()


@needs_bwrap
def test_network_is_unreachable(workspace: Path) -> None:
    outcome = BwrapSandbox(workspace).run(CONNECT_CMD)
    assert outcome.exit_code != 0
    assert "unreachable" in outcome.stderr.lower()


@needs_bwrap
def test_writes_outside_the_workspace_fail(workspace: Path, host_paths: list[Path]) -> None:
    tag = uuid.uuid4().hex
    read_only = [
        Path("/etc") / f"receipts-{tag}",
        Path("/var/tmp") / f"receipts-{tag}",
        Path.home() / f"receipts-{tag}",
    ]
    beside = workspace.resolve().parent / f"receipts-{tag}"
    host_paths.extend([*read_only, beside])
    box = BwrapSandbox(workspace)
    for target in read_only:
        outcome = box.run(f"echo x > {target}")
        assert outcome.exit_code != 0, target
        assert "Read-only file system" in outcome.stderr or "No such file" in outcome.stderr
        assert not target.exists()
    # The workspace's parent is under /tmp here, so a write there lands on the private
    # tmpfs: it may succeed inside, but it never reaches the host.
    box.run(f"echo x > {beside}")
    assert not beside.exists()
    inside = box.run("echo x > inside.txt && cat inside.txt")
    assert (inside.exit_code, inside.stdout) == (0, "x\n")
    assert (workspace / "inside.txt").read_text(encoding="utf-8") == "x\n"


@needs_bwrap
def test_the_root_cannot_be_remounted_writable(workspace: Path, host_paths: list[Path]) -> None:
    probe = Path("/var/tmp") / f"receipts-remount-{uuid.uuid4().hex}"
    host_paths.append(probe)
    outcome = BwrapSandbox(workspace).run(
        f"mount -o remount,bind,rw / 2>&1; echo x > {probe} && echo ESCAPED"
    )
    assert "ESCAPED" not in outcome.stdout
    assert not probe.exists()
    caps = BwrapSandbox(workspace).run("grep CapEff /proc/self/status").stdout
    assert caps.split()[-1] == "0000000000000000"


@needs_bwrap
def test_tmp_and_run_are_private(workspace: Path, host_paths: list[Path]) -> None:
    name = f"receipts-private-{uuid.uuid4().hex}"
    host_paths.append(Path("/tmp") / name)
    outcome = BwrapSandbox(workspace).run(f"echo x > /tmp/{name} && cat /tmp/{name}; ls -A /run")
    assert outcome.stdout == "x\n"
    assert not (Path("/tmp") / name).exists()


@needs_bwrap
def test_hidden_paths_are_empty_inside(workspace: Path) -> None:
    secret = workspace / "secret"
    secret.mkdir()
    (secret / "key.pem").write_text("synthetic-key", encoding="utf-8")
    (workspace / "token.txt").write_text("synthetic-token", encoding="utf-8")
    box = BwrapSandbox(workspace, hide_paths=[secret, workspace / "token.txt", "/no/such/path"])
    assert box.hidden_paths == (secret.resolve(), (workspace / "token.txt").resolve())
    outcome = box.run("ls -A secret; cat token.txt; echo end")
    assert outcome.stdout == "end\n"
    assert (secret / "key.pem").exists()


@needs_bwrap
def test_the_project_checkout_is_hidden_by_default(workspace: Path) -> None:
    root = project_root()
    assert root is not None
    outcome = BwrapSandbox(workspace).run(f"test -e {root / 'pyproject.toml'}")
    assert outcome.exit_code == 1


@needs_bwrap
def test_readonly_paths_are_visible_and_read_only(workspace: Path, tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "hello").write_text("#!/bin/sh\necho hello from tools\n", encoding="utf-8")
    (tools / "hello").chmod(0o755)
    box = BwrapSandbox(workspace, SandboxPolicy(readonly_paths=(tools,)))
    assert box.run(f"{tools}/hello").stdout == "hello from tools\n"
    write = box.run(f"touch {tools}/new")
    assert write.exit_code != 0 and "Read-only" in write.stderr


@needs_bwrap
def test_host_secrets_are_absent(workspace: Path, planted_secrets: dict[str, str]) -> None:
    outcome = BwrapSandbox(workspace).run("env; cat /proc/self/environ")
    for name, value in planted_secrets.items():
        assert f"{name}=" not in outcome.stdout
        assert value not in outcome.stdout


@needs_bwrap
def test_environment_home_and_cwd(workspace: Path) -> None:
    outcome = BwrapSandbox(workspace).run('pwd; echo "$HOME"; echo "$PATH"; id -u', cwd="sub")
    lines = outcome.stdout.splitlines()
    assert lines[:3] == [str(workspace.resolve() / "sub"), str(workspace.resolve()), DEFAULT_PATH]
    assert outcome.cwd == "sub"


@needs_bwrap
@pytest.mark.parametrize("own_session", [False, True])
def test_timeout_kills_every_child(workspace: Path, own_session: bool) -> None:
    marker = unique_marker()
    cmd = f"{background_sleeper(marker, own_session=own_session)} sleep 60"
    outcome = BwrapSandbox(workspace).run(cmd, timeout_s=0.7)
    assert outcome.timed_out and outcome.exit_code == TIMEOUT_EXIT_CODE
    assert wait_until_gone(marker)


@needs_bwrap
def test_background_processes_die_with_the_command(workspace: Path) -> None:
    marker = unique_marker()
    outcome = BwrapSandbox(workspace).run(f"{background_sleeper(marker, own_session=True)} true")
    assert outcome.exit_code == 0 and outcome.duration_s < 5
    assert wait_until_gone(marker)


@needs_bwrap
def test_output_is_capped_and_hashed(workspace: Path) -> None:
    box = BwrapSandbox(workspace, SandboxPolicy(max_output_chars=1000))
    outcome = box.run("head -c 5000 /dev/zero | tr '\\0' a")
    assert outcome.stdout_truncated and len(outcome.stdout) < 1100
    assert outcome.stdout_sha256 == hashlib.sha256(b"a" * 5000).hexdigest()


@needs_bwrap
def test_cwd_escape_is_rejected(workspace: Path) -> None:
    (workspace / "out").symlink_to("/etc")
    box = BwrapSandbox(workspace)
    for cwd in ("..", "/etc", "out"):
        with pytest.raises(CwdError):
            box.run("pwd", cwd=cwd)


@needs_bwrap
def test_rlimits_are_applied(workspace: Path) -> None:
    policy = SandboxPolicy(memory_mb=300, cpu_s=50, max_procs=40)
    outcome = BwrapSandbox(workspace, policy).run("ulimit -v; ulimit -t; ulimit -u")
    limits = rlimit_values(policy)
    assert outcome.stdout.split() == [str(limits["v"]), str(limits["t"]), str(limits["u"])]
    big = BwrapSandbox(workspace, policy).run('python3 -c "bytearray(600 * 1024 * 1024)"')
    assert big.exit_code == 1 and "MemoryError" in big.stderr


@needs_bwrap
def test_cpu_time_limit_stops_a_busy_loop(workspace: Path) -> None:
    outcome = BwrapSandbox(workspace, SandboxPolicy(cpu_s=1)).run("while :; do :; done")
    # Soft and hard limits are equal, so the kernel sends SIGKILL (SIGXCPU is possible).
    assert outcome.exit_code in (128 + 9, 128 + 24)
    assert not outcome.timed_out and outcome.duration_s < 10


@needs_bwrap
def test_exit_codes_signals_and_stdin(workspace: Path) -> None:
    box = BwrapSandbox(workspace)
    assert box.run("exit 7").exit_code == 7
    killed = box.run("kill -9 $$")
    assert (killed.exit_code, killed.stderr) == (137, "")
    assert box.run("cat", stdin="piped\n").stdout == "piped\n"
    assert box.run("cat").stdout == ""
    assert box.run("#" + "x" * (MAX_COMMAND_BYTES - 1)).exit_code == 0


def test_probe_reports_a_failing_bwrap(tmp_path: Path) -> None:
    fake = tmp_path / "bwrap"
    fake.write_text("#!/bin/sh\necho 'bwrap: synthetic failure' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    probe = probe_bwrap(str(fake))
    assert not probe.ok and "synthetic failure" in probe.detail
    silent = tmp_path / "silent-bwrap"
    silent.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    silent.chmod(0o755)
    assert "exit code 3" in probe_bwrap(str(silent)).detail


def test_project_root_is_none_outside_a_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bwrap_module, "__file__", "/nonexistent/a/b/c/bwrap.py")
    assert project_root() is None
