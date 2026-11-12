"""Tests for BwrapSandbox: command-line layout (always) and real isolation (bwrap only)."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import receipts
from receipts.sandbox import bwrap as bwrap_module
from receipts.sandbox.api import (
    CommandOutcome,
    HidesPaths,
    Sandbox,
    SandboxPolicy,
    SandboxUnavailableError,
)
from receipts.sandbox.base import LAUNCHER_ARG0, MAX_COMMAND_BYTES, CwdError, rlimit_values
from receipts.sandbox.bwrap import (
    SYSTEM_CREDENTIAL_PATHS,
    BwrapSandbox,
    default_hidden_paths,
    home_directories,
    mount_args,
    mount_plan,
    probe_bwrap,
    project_root,
    reaches,
)
from receipts.sandbox.cgroup import pids_cgroup_parent
from receipts.sandbox.env import DEFAULT_PATH
from receipts.sandbox.process import TIMEOUT_EXIT_CODE

from .helpers import (
    CONNECT_CMD,
    FORK_CMD,
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


def test_every_home_directory_is_scanned_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "home" / "first", tmp_path / "home" / "second"
    (first / ".ssh").mkdir(parents=True)
    (second / ".claude").mkdir(parents=True)
    (second / ".gitconfig").write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(bwrap_module, "home_directories", lambda: (first, second))
    hidden = default_hidden_paths(project=tmp_path / "no-project")
    for path in (first / ".ssh", second / ".claude", second / ".gitconfig"):
        assert path.resolve() in hidden


def test_home_directories_lists_home_entries_and_password_homes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home_root = tmp_path / "home"
    for name in ("alice", "bob"):
        (home_root / name).mkdir(parents=True)
    (home_root / "note.txt").write_text("not a home", encoding="utf-8")
    service = tmp_path / "var" / "lib" / "service"
    service.mkdir(parents=True)
    homes = home_directories(home_root, [str(service), "", "relative/home", "/nonexistent/x"])
    assert homes[0] == Path.home().resolve() and Path("/root").resolve() in homes
    for path in (home_root / "alice", home_root / "bob", service):
        assert path.resolve() in homes
    assert (home_root / "note.txt").resolve() not in homes
    assert len(homes) == len(set(homes))
    assert home_directories(tmp_path / "missing", [])[0] == Path.home().resolve()

    class Entry:
        pw_dir = str(service)

    monkeypatch.setattr(pwd, "getpwall", lambda: [Entry()])
    assert service.resolve() in home_directories(tmp_path / "missing")


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


SYNTHETIC_SHA = "0123456789abcdef0123456789abcdef01234567"


def place_module(monkeypatch: pytest.MonkeyPatch, src: Path) -> None:
    """Make bwrap.py look as if it were imported from the package under ``src``."""
    module = src / "receipts" / "sandbox" / "bwrap.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bwrap_module, "__file__", str(module))


def test_project_root_finds_the_checkout_above_a_code_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> None:
    # tools/snapshot_code.sh extracts only src/ under runs/code/<sha>/ (review N18).
    checkout = make_checkout(tmp_path / "checkout")
    snapshot = checkout / "runs" / "code" / SYNTHETIC_SHA
    place_module(monkeypatch, snapshot / "src")
    (snapshot / "SNAPSHOT_OF").write_text(SYNTHETIC_SHA + "\n", encoding="utf-8")
    assert project_root() == checkout.resolve()
    assert checkout.resolve() in default_hidden_paths([])


def test_project_root_returns_the_outermost_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> None:
    outer = make_checkout(tmp_path / "checkout")
    worktree = make_checkout(outer / ".claude" / "worktrees" / "synthetic")
    place_module(monkeypatch, worktree / "src")
    assert project_root() == outer.resolve()


def test_project_root_is_none_for_a_snapshot_outside_any_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    place_module(monkeypatch, tmp_path / "loose" / "code" / SYNTHETIC_SHA / "src")
    assert project_root() is None


def test_a_hidden_checkout_is_mounted_before_the_toolchain_and_workspace_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> None:
    # tmp_path is under /tmp, which every sandbox makes private; without that tmpfs the
    # checkout itself must be what hides these paths.
    monkeypatch.setattr(bwrap_module, "PRIVATE_DIRS", ())
    checkout = make_checkout(tmp_path / "checkout").resolve()
    toolchain = checkout / "runs" / "toolchains" / "bench-py311"
    ws = checkout / "runs" / "work" / "smoke" / "run-1"
    other = checkout / "runs" / "work" / "smoke" / "run-2"
    for directory in (toolchain, ws, other):
        directory.mkdir(parents=True)
    order = pairs(mount_args(ws, [toolchain], [checkout]))
    cover = order.index(("--tmpfs", str(checkout)))
    assert cover < order.index(("--ro-bind", str(toolchain))) < order.index(("--bind", str(ws)))
    plan = mount_plan(ws, [toolchain], [checkout])
    for hidden in (checkout, checkout / "bench" / "tasks", checkout / "private", other):
        assert not reaches(hidden, plan), hidden
    assert reaches(toolchain / "bin", plan) and reaches(ws / "src", plan)
    assert reaches(checkout / "bench", mount_plan(ws, [toolchain], []))


def test_a_mount_at_or_above_the_checkout_decides_whether_it_is_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> None:
    monkeypatch.setattr(bwrap_module, "PRIVATE_DIRS", ())
    checkout = make_checkout(tmp_path / "checkout").resolve()
    ws = tmp_path / "ws"
    ws.mkdir()
    # A read-only path or the workspace at the checkout itself is mounted after its
    # tmpfs and shows it again; one above it is mounted before and stays covered.
    assert reaches(checkout, mount_plan(ws, [checkout], [checkout]))
    assert reaches(checkout / "bench", mount_plan(checkout, [], [checkout]))
    assert not reaches(checkout / "bench", mount_plan(ws, [tmp_path], [checkout]))
    assert not reaches(checkout / "bench", mount_plan(tmp_path, [], [checkout]))
    assert reaches(checkout / "bench", mount_plan(ws, [], [checkout / "private"]))


def test_hides_and_shown_within_follow_the_sandbox_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_checkout: Callable[[Path], Path]
) -> None:
    monkeypatch.setattr(bwrap_module, "PRIVATE_DIRS", ())
    checkout = make_checkout(tmp_path / "checkout").resolve()
    toolchain = checkout / "runs" / "toolchains" / "bench-py311"
    ws = checkout / "runs" / "work" / "smoke" / "run-1"
    for directory in (toolchain, ws):
        directory.mkdir(parents=True)
    policy = SandboxPolicy(readonly_paths=(toolchain,))
    box = BwrapSandbox(ws, policy, bwrap="true", hide_paths=[checkout])
    assert isinstance(box, HidesPaths)
    assert box.hides(checkout) and box.hides(checkout / "bench" / "tasks")
    assert not box.hides(toolchain) and not box.hides(ws / "src")
    assert box.shown_within(checkout) == (toolchain, ws)
    assert box.shown_within(toolchain) == ()
    assert not BwrapSandbox(ws, policy, bwrap="true", hide_paths=[]).hides(checkout)


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
    probe = probe_bwrap()
    assert probe.ok
    box = BwrapSandbox(workspace)
    assert f"process limit: {box.process_limit}" in probe.detail
    assert isinstance(box, Sandbox)
    assert (box.backend, box.confines_writes) == ("bwrap", True)
    assert Path(box.executable).is_absolute()


@needs_bwrap
def test_other_homes_credentials_are_hidden_inside(workspace: Path, tmp_path: Path) -> None:
    other = tmp_path / "home" / "other"
    (other / ".ssh").mkdir(parents=True)
    (other / ".ssh" / "id_synthetic").write_text("synthetic-key", encoding="utf-8")
    (other / ".gitconfig").write_text("[user]\n\tname = synthetic\n", encoding="utf-8")
    hidden = default_hidden_paths([other], tmp_path / "no-project")
    outcome = BwrapSandbox(workspace, hide_paths=hidden).run(
        f"ls -A {other / '.ssh'} | wc -l; stat -c %s {other / '.gitconfig'}"
    )
    assert outcome.stdout.split() == ["0", "0"]


@needs_bwrap
def test_max_procs_is_enforced(workspace: Path) -> None:
    box = BwrapSandbox(workspace, SandboxPolicy(max_procs=10, timeout_s=60))
    if box.process_limit == "none":
        pytest.skip("running as root without a writable pids cgroup: max_procs is not enforced")
    started, failed = map(int, box.run(FORK_CMD).stdout.split())
    assert started < 10 and failed > 50
    parent = pids_cgroup_parent()
    if box.process_limit == "cgroup" and parent is not None:
        # /sys is read-only inside, so the command cannot move itself to the parent.
        escape = box.run(f"echo $$ > {parent / 'cgroup.procs'} && echo ESCAPED")
        assert "ESCAPED" not in escape.stdout
        assert "Read-only file system" in escape.stderr


@needs_bwrap
def test_a_vanished_readonly_path_is_a_sandbox_failure(workspace: Path, tmp_path: Path) -> None:
    tools = tmp_path / "toolchain"
    tools.mkdir()
    box = BwrapSandbox(workspace, SandboxPolicy(readonly_paths=(tools,)))
    assert box.run("true").exit_code == 0
    shutil.rmtree(tools)
    with pytest.raises(SandboxUnavailableError, match="read-only paths no longer exist"):
        box.run("true")


@needs_bwrap
def test_a_vanished_hidden_path_is_skipped(workspace: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.mkdir()
    box = BwrapSandbox(workspace, hide_paths=[secret])
    secret.rmdir()
    assert box.run("echo ok").stdout == "ok\n"


def test_a_bwrap_that_never_starts_the_command_raises(workspace: Path, tmp_path: Path) -> None:
    fake = tmp_path / "bwrap"
    fake.write_text(
        '#!/bin/sh\necho "bwrap: Can\'t find source path /synthetic" >&2\nexit 1\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    box = BwrapSandbox(workspace, bwrap=str(fake), hide_paths=())
    with pytest.raises(SandboxUnavailableError, match=r"did not start the command.*synthetic"):
        box.run("true")


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


#: Run in a child Python that imports receipts from a code snapshot: build a sandbox with
#: the default hidden paths on a workspace inside the checkout and look around in it.
SNAPSHOT_PROBE = """
import json, sys
from pathlib import Path
import receipts
from receipts.sandbox.bwrap import BwrapSandbox, project_root
checkout, ws = Path(sys.argv[1]), Path(sys.argv[2])
box = BwrapSandbox(ws)
def run(cmd):
    outcome = box.run(cmd)
    return [outcome.exit_code, outcome.stdout]
print(json.dumps({
    "imported_from": receipts.__file__,
    "project_root": str(project_root()),
    "bench": run(f"ls -A {checkout}/bench"),
    "hidden_check": run(f"cat {checkout}/bench/tasks/py-synthetic/hidden/check.py"),
    "checkout": run(f"ls -A {checkout}"),
    "workspace": run("echo synthetic > made.txt && cat made.txt"),
}))
"""


@needs_bwrap
def test_a_run_from_a_code_snapshot_cannot_list_the_checkouts_bench(
    outside_tmp: Path, make_checkout: Callable[[Path], Path]
) -> None:
    # The checkout lies outside /tmp, so only the sandbox's own hiding can keep it out.
    checkout = make_checkout(outside_tmp / "checkout")
    snapshot = checkout / "runs" / "code" / SYNTHETIC_SHA
    package = Path(receipts.__file__).resolve().parent
    shutil.copytree(
        package, snapshot / "src" / "receipts", ignore=shutil.ignore_patterns("__pycache__")
    )
    (snapshot / "SNAPSHOT_OF").write_text(SYNTHETIC_SHA + "\n", encoding="utf-8")
    ws = checkout / "runs" / "work" / "smoke" / "run-1"
    ws.mkdir(parents=True)
    env = {**os.environ, "PYTHONPATH": str(snapshot / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    child = subprocess.run(
        [sys.executable, "-c", SNAPSHOT_PROBE, str(checkout), str(ws)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=120,
    )
    seen = json.loads(child.stdout)
    assert Path(seen["imported_from"]).is_relative_to(snapshot / "src")
    assert seen["project_root"] == str(checkout)
    assert seen["bench"][0] != 0 and seen["bench"][1] == ""
    assert seen["hidden_check"][0] != 0 and seen["hidden_check"][1] == ""
    assert seen["checkout"] == [0, "runs\n"]
    assert seen["workspace"] == [0, "synthetic\n"]
    assert (ws / "made.txt").read_text(encoding="utf-8") == "synthetic\n"


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


@needs_bwrap
def test_probe_reports_a_trivial_command_that_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BwrapSandbox, "run", failing_true)
    probe = probe_bwrap()
    assert not probe.ok and probe.detail == "bubblewrap fails here: synthetic: true failed"
