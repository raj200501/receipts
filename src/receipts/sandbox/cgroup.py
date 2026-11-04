"""Enforce ``max_procs`` with the cgroup pids controller.

``ulimit -u`` (``RLIMIT_NPROC``) does not bind processes of the host's root user, and
a bubblewrap or ``unshare`` sandbox started by root keeps that user (it is mapped to
itself), so under root a command could start any number of processes until its
timeout. A per-command cgroup whose ``pids.max`` is the policy's ``max_procs`` binds
every user, root included:

- :func:`pids_cgroup_parent` finds the directory of this process's own cgroup in a
  hierarchy with the pids controller and checks that a child created there gets a
  ``pids.max`` file (cgroup v1 with a writable ``pids`` hierarchy, as in this
  project's container; or cgroup v2 when the pids controller is enabled for this
  cgroup's children). It returns None when that does not work, and the backends then
  fall back to ``RLIMIT_NPROC`` alone.
- :class:`PidsCgroup` makes one child cgroup per command and wraps the launch so that
  its first host process joins the cgroup before it starts anything (a short bash
  script writes its own PID to ``cgroup.procs``, then ``exec``\\ s the backend); every
  process it starts stays in the cgroup. ``pids.max`` counts every task (threads
  included) of the sandbox, its launcher among them, as Docker's ``--pids-limit``
  does. When the command is done, any task left in the cgroup is killed (through a
  pidfd, after checking that the task is still a member, so a reused PID is never
  signalled) and the cgroup is removed.

A command cannot move itself out: bubblewrap mounts ``/sys`` read-only, and
:class:`~receipts.sandbox.unshare.UnshareSandbox` covers ``/sys/fs/cgroup`` with an
empty tmpfs.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import re
import signal
import time
import uuid
from pathlib import Path, PurePosixPath
from types import TracebackType

from receipts.sandbox.api import SandboxUnavailableError
from receipts.sandbox.process import Launch

#: Name prefix of every cgroup this module creates.
CGROUP_PREFIX = "receipts-"

#: Exit code of the join script when the launch could not join its cgroup.
JOIN_FAILED_EXIT_CODE = 125

#: The script that joins the cgroup (``$1`` is its ``cgroup.procs``) and runs the rest.
JOIN_SCRIPT = (
    'printf "%s\\n" "$$" > "$1" || {\n'
    '  echo "receipts: cannot join the process-limit cgroup $1" >&2\n'
    f"  exit {JOIN_FAILED_EXIT_CODE}\n"
    "}\n"
    "shift\n"
    'exec "$@"'
)

#: ``$0`` of the join script (it shows up in process listings).
JOIN_ARG0 = "receipts-cgroup"

_OWN_NAME = re.compile(rf"{re.escape(CGROUP_PREFIX)}(?:probe-)?(\d+)-[0-9a-f]{{12}}")
_OCTAL = re.compile(r"\\([0-7]{3})")


def _unescape(field: str) -> str:
    """Undo the octal escapes ``/proc/self/mountinfo`` uses for spaces and the like."""
    return _OCTAL.sub(lambda match: chr(int(match.group(1), 8)), field)


def pids_cgroup_dir(mountinfo: str, cgroups: str) -> Path | None:
    """The directory of this process's cgroup in a hierarchy with the pids controller.

    Args:
        mountinfo: The text of ``/proc/self/mountinfo``.
        cgroups: The text of ``/proc/self/cgroup``.

    Returns:
        The directory in a cgroup v1 ``pids`` mount, else in the cgroup v2 mount,
        else None (also when this process's cgroup lies outside the mounted tree).
    """
    v1_path: str | None = None
    v2_path: str | None = None
    for line in cgroups.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, path = parts
        if "pids" in controllers.split(","):
            v1_path = path
        elif hierarchy == "0" and not controllers:
            v2_path = path
    candidates: list[tuple[int, Path]] = []
    for line in mountinfo.splitlines():
        left, sep, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if not sep or len(fields) < 5 or len(tail) < 3:
            continue
        fstype, options = tail[0], tail[2].split(",")
        if fstype == "cgroup" and "pids" in options and v1_path is not None:
            rank, own = 0, v1_path
        elif fstype == "cgroup2" and v2_path is not None:
            rank, own = 1, v2_path
        else:
            continue
        root, mountpoint = PurePosixPath(_unescape(fields[3])), _unescape(fields[4])
        if not PurePosixPath(own).is_relative_to(root):
            continue
        candidates.append((rank, Path(mountpoint) / PurePosixPath(own).relative_to(root)))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_stale(parent: Path) -> int:
    """Remove empty cgroups this module left under ``parent`` for processes that are gone.

    Only directories named like this module's (``receipts-<pid>-<hex>``) whose owning
    PID no longer exists are removed; ``rmdir`` refuses any that still has tasks.

    Returns:
        How many were removed.
    """
    removed = 0
    with contextlib.suppress(OSError):
        for child in parent.iterdir():
            match = _OWN_NAME.fullmatch(child.name)
            if match is None or _alive(int(match.group(1))):
                continue
            with contextlib.suppress(OSError):
                child.rmdir()
                removed += 1
    return removed


def _child_name(kind: str = "") -> str:
    return f"{CGROUP_PREFIX}{kind}{os.getpid()}-{uuid.uuid4().hex[:12]}"


def pids_cgroup_parent(
    mountinfo: Path = Path("/proc/self/mountinfo"), cgroups: Path = Path("/proc/self/cgroup")
) -> Path | None:
    """Where :class:`PidsCgroup` can create per-command cgroups, or None.

    The directory from :func:`pids_cgroup_dir` is checked by creating a probe child
    (it must get a ``pids.max`` file) and removing it again; stale cgroups this module
    left there are swept first (:func:`sweep_stale`).
    """
    try:
        parent = pids_cgroup_dir(
            mountinfo.read_text(encoding="utf-8"), cgroups.read_text(encoding="utf-8")
        )
    except OSError:
        return None
    if parent is None or not parent.is_dir():
        return None
    sweep_stale(parent)
    probe = parent / _child_name("probe-")
    try:
        probe.mkdir()
    except OSError:
        return None
    try:
        return parent if (probe / "pids.max").is_file() else None
    finally:
        with contextlib.suppress(OSError):
            probe.rmdir()


def _member(pid: int, name: str) -> bool:
    """True when process ``pid`` belongs to the cgroup named ``name`` (in any hierarchy)."""
    try:
        text = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(name in PurePosixPath(line.split(":", 2)[-1]).parts for line in text.splitlines())


def kill_member(pid: int, name: str) -> bool:
    """SIGKILL ``pid`` if it still belongs to cgroup ``name``; True if a signal was sent.

    A pidfd is opened first and membership checked after, so if ``pid`` exited and
    its number was reused by a process outside the cgroup, nothing is signalled.
    """
    try:
        pidfd = os.pidfd_open(pid)
    except OSError:  # gone already
        return False
    try:
        if not _member(pid, name):
            return False
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        return True
    except OSError:
        return False
    finally:
        os.close(pidfd)


class PidsCgroup:
    """A per-command cgroup whose ``pids.max`` bounds every task started in it.

    Use it as a context manager: entering creates the cgroup, leaving kills any task
    still in it and removes it.

    Args:
        parent: A directory from :func:`pids_cgroup_parent`.
        max_pids: The ``pids.max`` value (``policy.max_procs``).
        bash: The bash executable that runs :data:`JOIN_SCRIPT`.

    Raises:
        ValueError: ``max_pids`` is not positive.
    """

    def __init__(self, parent: Path, max_pids: int, bash: str) -> None:
        if max_pids <= 0:
            raise ValueError(f"max_pids must be positive, got {max_pids!r}")
        self._path = parent / _child_name()
        self._max = max_pids
        self._bash = bash

    @property
    def path(self) -> Path:
        """The cgroup's directory."""
        return self._path

    def __enter__(self) -> PidsCgroup:
        """Create the cgroup and set ``pids.max``.

        Raises:
            SandboxUnavailableError: The cgroup could not be created or limited.
        """
        try:
            self._path.mkdir()
            (self._path / "pids.max").write_text(f"{self._max}\n", encoding="utf-8")
        except OSError as exc:
            self.remove(timeout_s=0.0)
            raise SandboxUnavailableError(
                f"cannot create the process-limit cgroup {self._path}: {exc}"
            ) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Kill what is left in the cgroup and remove it."""
        self.remove()

    def wrap(self, launch: Launch) -> Launch:
        """``launch`` with its command line run by :data:`JOIN_SCRIPT` inside this cgroup."""
        procs = str(self._path / "cgroup.procs")
        return dataclasses.replace(
            launch, argv=(self._bash, "-c", JOIN_SCRIPT, JOIN_ARG0, procs, *launch.argv)
        )

    def pids(self) -> list[int]:
        """PIDs of the processes in the cgroup (empty once it is gone)."""
        try:
            text = (self._path / "cgroup.procs").read_text(encoding="utf-8")
        except OSError:
            return []
        return [int(line) for line in text.split() if line.isdigit()]

    def remove(self, timeout_s: float = 5.0) -> bool:
        """Kill every task left in the cgroup, then remove it; True once it is gone.

        Tasks that are already exiting can keep the cgroup busy for a moment, so
        removal is retried until ``timeout_s`` has passed. A cgroup that still cannot
        be removed is left for :func:`sweep_stale`.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            for pid in self.pids():
                kill_member(pid, self._path.name)
            try:
                self._path.rmdir()
            except FileNotFoundError:
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)
            else:
                return True
