"""Tests for enforcing ``max_procs`` with the cgroup pids controller.

Parsing tests use synthetic ``/proc/self/mountinfo`` and ``/proc/self/cgroup`` text.
Tests marked with ``needs_cgroup`` create real cgroups and skip when this machine has
no writable pids hierarchy.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from receipts.sandbox import cgroup as cgroup_module
from receipts.sandbox.api import SandboxUnavailableError
from receipts.sandbox.cgroup import (
    CGROUP_PREFIX,
    JOIN_FAILED_EXIT_CODE,
    PidsCgroup,
    kill_member,
    pids_cgroup_dir,
    pids_cgroup_parent,
    sweep_stale,
)
from receipts.sandbox.process import Launch, run_launch

BASH = shutil.which("bash") or "/bin/bash"
PARENT = pids_cgroup_parent()
needs_cgroup = pytest.mark.skipif(PARENT is None, reason="no writable pids cgroup here")

#: Synthetic mountinfo lines: a cgroup v1 pids mount, a v2 mount, and an ext4 root.
V1_PIDS = "45 37 0:37 / /sys/fs/cgroup/pids rw,relatime - cgroup cgroup rw,pids"
V1_MEMORY = "41 37 0:33 / /sys/fs/cgroup/memory rw,relatime - cgroup cgroup rw,memory"
V2 = "47 37 0:39 / /sys/fs/cgroup/unified rw,relatime - cgroup2 cgroup2 rw"
ROOT = "22 1 253:1 / / rw,relatime - ext4 /dev/vda rw"

#: Python that forks up to 60 children and prints how many forks succeeded and failed.
FORKER = (
    "import os\n"
    "r, w = os.pipe()\n"
    "started = failed = 0\n"
    "for _ in range(60):\n"
    "    try:\n"
    "        pid = os.fork()\n"
    "    except OSError:\n"
    "        failed += 1\n"
    "        continue\n"
    "    if pid == 0:\n"
    "        os.close(w)\n"
    "        os.read(r, 1)\n"
    "        os._exit(0)\n"
    "    started += 1\n"
    "os.close(w)\n"
    "print(started, failed)\n"
)


def test_v1_pids_hierarchy_is_found() -> None:
    mountinfo = "\n".join([ROOT, V1_MEMORY, V1_PIDS, V2])
    cgroups = "8:pids:/\n4:memory:/job\n0::/\n"
    assert pids_cgroup_dir(mountinfo, cgroups) == Path("/sys/fs/cgroup/pids")
    nested = "8:pids:/runner/job-1\n0::/\n"
    assert pids_cgroup_dir(mountinfo, nested) == Path("/sys/fs/cgroup/pids/runner/job-1")


def test_a_mount_of_a_subtree_maps_the_path_relative_to_its_root() -> None:
    mounted = "45 37 0:37 /docker/abc /sys/fs/cgroup/pids ro - cgroup cgroup rw,pids"
    assert pids_cgroup_dir(mounted, "8:pids:/docker/abc/inner\n") == Path(
        "/sys/fs/cgroup/pids/inner"
    )
    assert pids_cgroup_dir(mounted, "8:pids:/elsewhere\n") is None


def test_v2_is_used_without_a_v1_pids_hierarchy() -> None:
    v2_only = "30 22 0:26 / /sys/fs/cgroup rw - cgroup2 cgroup2 rw,nsdelegate"
    assert pids_cgroup_dir(v2_only, "0::/user.slice/job\n") == Path("/sys/fs/cgroup/user.slice/job")
    mountinfo = "\n".join([V2, V1_PIDS])
    assert pids_cgroup_dir(mountinfo, "0::/\n8:pids:/\n") == Path("/sys/fs/cgroup/pids")


def test_escaped_mount_points_and_junk_lines() -> None:
    spaced = r"45 37 0:37 / /mnt/cg\040pids rw - cgroup cgroup rw,pids"
    assert pids_cgroup_dir(spaced, "8:pids:/\n") == Path("/mnt/cg pids")
    junk = "\n".join(["not a mountinfo line", "1 2 3 - cgroup", V1_MEMORY])
    assert pids_cgroup_dir(junk, "bad line\n8:pids:/\n") is None
    assert pids_cgroup_dir(V1_PIDS, "4:memory:/\n") is None


def test_parent_is_none_without_pids_max_and_cleans_its_probe(tmp_path: Path) -> None:
    fake = tmp_path / "pids"
    fake.mkdir()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(f"45 37 0:37 / {fake} rw - cgroup cgroup rw,pids\n", encoding="utf-8")
    cgroups = tmp_path / "cgroup"
    cgroups.write_text("8:pids:/\n", encoding="utf-8")
    assert pids_cgroup_parent(mountinfo, cgroups) is None
    assert list(fake.iterdir()) == []
    assert pids_cgroup_parent(tmp_path / "missing", cgroups) is None
    cgroups.write_text("8:pids:/not-there\n", encoding="utf-8")
    assert pids_cgroup_parent(mountinfo, cgroups) is None


def test_parent_is_none_when_no_child_can_be_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "pids"
    (fake / "taken").mkdir(parents=True)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(f"45 37 0:37 / {fake} rw - cgroup cgroup rw,pids\n", encoding="utf-8")
    cgroups = tmp_path / "cgroup"
    cgroups.write_text("8:pids:/\n", encoding="utf-8")
    monkeypatch.setattr(cgroup_module, "_child_name", lambda kind="": "taken")
    assert pids_cgroup_parent(mountinfo, cgroups) is None


def test_sweep_removes_only_empty_cgroups_of_dead_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = tmp_path / f"{CGROUP_PREFIX}999999999-0123456789ab"
    dead_probe = tmp_path / f"{CGROUP_PREFIX}probe-999999999-0123456789ab"
    live = tmp_path / f"{CGROUP_PREFIX}{os.getpid()}-0123456789ab"
    busy = tmp_path / f"{CGROUP_PREFIX}999999998-0123456789ab"
    other = tmp_path / "unrelated"
    for path in (dead, dead_probe, live, busy, other):
        path.mkdir()
    (busy / "task").write_text("synthetic", encoding="utf-8")
    assert sweep_stale(tmp_path) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([live.name, busy.name, "unrelated"])
    assert sweep_stale(tmp_path / "missing") == 0

    def denied(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", denied)
    assert sweep_stale(tmp_path) == 0


def test_cgroup_arguments_and_creation_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_pids"):
        PidsCgroup(tmp_path, 0, BASH)
    with (
        pytest.raises(SandboxUnavailableError, match="process-limit cgroup"),
        PidsCgroup(tmp_path / "missing", 5, BASH),
    ):
        pass


def test_wrap_runs_the_launch_through_the_join_script(tmp_path: Path) -> None:
    group = PidsCgroup(tmp_path, 5, BASH)
    wrapped = group.wrap(Launch(argv=("/bin/true", "x"), env={}, cwd=tmp_path, pass_fds=(9,)))
    assert wrapped.argv[:2] == (BASH, "-c") and wrapped.argv[-2:] == ("/bin/true", "x")
    assert wrapped.argv[4] == str(group.path / "cgroup.procs")
    assert wrapped.pass_fds == (9,) and group.path.parent == tmp_path


def test_join_failure_stops_before_running_anything(tmp_path: Path) -> None:
    group = PidsCgroup(tmp_path, 5, BASH)  # never entered: its directory does not exist
    launch = group.wrap(Launch(argv=(BASH, "-c", "echo ran"), env={}, cwd=tmp_path))
    result = run_launch(launch, timeout_s=10)
    assert result.exit_code == JOIN_FAILED_EXIT_CODE and result.stdout.text == ""
    assert "cannot join the process-limit cgroup" in result.stderr.text


def test_pids_and_remove_on_plain_directories(tmp_path: Path) -> None:
    group = PidsCgroup(tmp_path, 5, BASH)
    assert group.pids() == []
    assert group.remove() is True  # nothing there
    group.path.mkdir()
    (group.path / "cgroup.procs").write_text("12\nbad\n", encoding="utf-8")
    assert group.pids() == [12]
    assert group.remove(timeout_s=0.05) is False  # a plain directory with a file stays


def test_kill_member_spares_processes_outside_the_cgroup() -> None:
    proc = subprocess.Popen(["sleep", "30"])
    try:
        assert kill_member(proc.pid, f"{CGROUP_PREFIX}not-a-real-group") is False
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()
    assert kill_member(proc.pid, "anything") is False  # gone


def test_kill_member_reports_a_refused_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = subprocess.Popen(["sleep", "30"])
    try:
        monkeypatch.setattr(cgroup_module, "_member", lambda pid, name: True)

        def refused(fd: int, sig: int) -> None:
            raise PermissionError

        monkeypatch.setattr(signal, "pidfd_send_signal", refused)
        assert kill_member(proc.pid, "anything") is False
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_membership_of_a_process_that_is_gone() -> None:
    proc = subprocess.Popen(["true"])
    proc.wait()
    assert cgroup_module._member(proc.pid, "anything") is False


@needs_cgroup
def test_a_real_cgroup_limits_forks_and_is_removed(tmp_path: Path) -> None:
    assert PARENT is not None
    with PidsCgroup(PARENT, 10, BASH) as group:
        assert (group.path / "pids.max").read_text(encoding="utf-8").strip() == "10"
        launch = group.wrap(
            Launch(argv=("python3", "-c", FORKER), env=dict(os.environ), cwd=tmp_path)
        )
        result = run_launch(launch, timeout_s=60)
        started, failed = map(int, result.stdout.text.split())
        assert started < 10 and failed > 50
        path = group.path
    assert not path.exists()


@needs_cgroup
def test_removal_kills_what_is_left(tmp_path: Path) -> None:
    assert PARENT is not None
    group = PidsCgroup(PARENT, 10, BASH)
    with group:
        launch = group.wrap(Launch(argv=("sleep", "60"), env=dict(os.environ), cwd=tmp_path))
        proc = subprocess.Popen(list(launch.argv), start_new_session=True)
        deadline = time.monotonic() + 10
        while proc.pid not in group.pids() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert group.pids() == [proc.pid]
    assert proc.wait(timeout=10) == -9
    assert not group.path.exists()
