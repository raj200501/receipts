"""UnshareSandbox: ``unshare -rn`` network isolation only. IT DOES NOT CONFINE WRITES.

WARNING: a command in this sandbox can read and write anything the invoking user can,
anywhere on the host outside the private directories listed below. It removes network
access (a new, empty network namespace), starts from the clean environment, applies
rlimits, and hides host sockets, but nothing more. Per DECISIONS D5 it may run only
this project's own generated tasks: never subject agents on third-party task
repositories, graders, or benchmark scripts. Prefer
:class:`~receipts.sandbox.bwrap.BwrapSandbox` or
:class:`~receipts.sandbox.docker.DockerSandbox` whenever either works;
:func:`receipts.sandbox.select.make_sandbox` uses this backend only when the caller
passes ``allow_unconfined=True``.

Each command runs as ``unshare -rn --pid --fork --kill-child --mount-proc``: user and
network namespaces as in D5, plus a PID namespace that ties every process the command
starts to the launcher, so a timeout kills them all (including ones that start their
own session). ``--mount-proc`` gives that PID namespace its own ``/proc`` inside a
private mount namespace, so ``/proc/<pid>`` matches the PIDs the command sees.

In that mount namespace the launcher first covers :data:`PRIVATE_DIRS` (``/tmp``,
``/run``, ``/sys/fs/cgroup``) with empty tmpfs mounts, so host Unix sockets there (the
Docker daemon's ``/run/docker.sock``, agent sockets under ``/tmp``) are out of reach
and the command cannot move itself out of its pids cgroup. The workspace and any
``policy.readonly_paths`` entry under a covered directory are bound back at the same
path (through a descriptor opened before the cover, so the bind sees the host
directory). Writes to those paths reach the host; writes elsewhere under the covered
directories land in the private tmpfs and vanish with the command. If a setup step
fails, :meth:`~receipts.sandbox.base.ProcessSandbox.run` raises
:class:`~receipts.sandbox.api.SandboxUnavailableError` (the launcher reports through a
status pipe that it started the command).

``max_procs`` is enforced with a per-command pids cgroup when one is available
(:mod:`receipts.sandbox.cgroup`); otherwise only ``ulimit -u`` applies, which does not
bind the host's root user.
"""

from __future__ import annotations

import shlex
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    LAUNCHER_ARG0,
    BackendProbe,
    ProcessSandbox,
    StartReport,
    check_readonly_paths,
    find_executable,
    launcher_script,
    require_paths,
    rlimit_values,
)
from receipts.sandbox.process import DEFAULT_MAX_CAPTURE_BYTES, Launch

#: Host directories covered by an empty tmpfs inside the sandbox, with their modes.
PRIVATE_DIRS: tuple[tuple[str, str], ...] = (
    ("/tmp", "1777"),
    ("/run", "0755"),
    ("/sys/fs/cgroup", "0755"),
)


def _under(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def private_mounts(
    keep: Sequence[Path],
    *,
    mount: str,
    mkdir: str,
    private_dirs: Sequence[tuple[str, str]] = PRIVATE_DIRS,
) -> list[str]:
    """Launcher prologue steps that cover ``private_dirs`` and bind ``keep`` back.

    Args:
        keep: Host paths (the workspace, read-only paths) that must stay visible.
        mount: The util-linux ``mount`` executable.
        mkdir: The ``mkdir`` executable.
        private_dirs: ``(directory, mode)`` pairs to cover; directories that do not
            exist on the host are skipped.

    Returns:
        Shell steps, in order: open a descriptor on each kept path under a covered
        directory, mount the tmpfs covers, recreate each kept path (a directory, or an
        empty file for a file) and bind its descriptor onto it, close the descriptors.
    """
    covered = [(Path(d), mode) for d, mode in private_dirs if Path(d).is_dir()]
    rebind = sorted(
        {p for p in keep if any(_under(p, d) for d, _ in covered)},
        key=lambda p: (len(p.parts), str(p)),
    )
    steps = []
    for index, path in enumerate(rebind):
        steps.append(f"exec {{_receipts_keep{index}}}<{shlex.quote(str(path))}")
    for directory, mode in covered:
        options = f"mode={mode},nosuid,nodev"
        steps.append(
            f"{mount} -t tmpfs -o {options} receipts-private {shlex.quote(str(directory))}"
        )
    for index, path in enumerate(rebind):
        target = shlex.quote(str(path))
        if path.is_dir():
            make = f"{mkdir} -p -- {target}"
        else:
            make = f"{mkdir} -p -- {shlex.quote(str(path.parent))} && : > {target}"
        source = f'"/proc/self/fd/$_receipts_keep{index}"'
        steps.append(f"{make} && {mount} --no-canonicalize --bind {source} {target}")
    if rebind:
        closes = " ".join(f"{{_receipts_keep{index}}}<&-" for index in range(len(rebind)))
        names = " ".join(f"_receipts_keep{index}" for index in range(len(rebind)))
        steps.append(f"exec {closes} && unset {names}")
    return steps


class UnshareSandbox(ProcessSandbox):
    """Network-isolated commands that are NOT write-confined (see the module warning).

    Args:
        workspace: The workspace directory (commands start there, but may write
            anywhere the invoking user can).
        policy: Limits and allowances; :class:`SandboxPolicy` defaults if None.
            ``readonly_paths`` must exist; they are bound back when under a private
            directory, but not made read-only.
        unshare: The util-linux ``unshare`` executable.
        max_capture_bytes: Stream ceiling before the command is stopped.

    Raises:
        SandboxUnavailableError: ``unshare``, ``mount``, ``mkdir``, or bash is not
            installed.
        ValueError: The workspace, the policy, or a read-only path is invalid.
    """

    backend_name: ClassVar[str] = "unshare"
    confines_writes: ClassVar[bool] = False
    start_report: ClassVar[StartReport] = "fd"
    uses_pids_cgroup: ClassVar[bool] = True

    def __init__(
        self,
        workspace: str | Path,
        policy: SandboxPolicy | None = None,
        *,
        unshare: str = "unshare",
        max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    ) -> None:
        super().__init__(workspace, policy, max_capture_bytes=max_capture_bytes)
        self._unshare = find_executable(unshare, "unshare")
        self._mount = find_executable("mount", "mount")
        self._mkdir = find_executable("mkdir", "mkdir")
        self._bash = find_executable("bash", "bash")
        self._readonly = check_readonly_paths(self._policy.readonly_paths)

    @property
    def executable(self) -> str:
        """The unshare executable in use."""
        return self._unshare

    def launch(
        self, cmd: str, cwd: Path, *, interactive: bool = False, status_fd: int | None = None
    ) -> Launch:
        """The unshare command line for ``cmd``, started in host directory ``cwd``.

        Raises:
            SandboxUnavailableError: A read-only path no longer exists.
        """
        require_paths(self._readonly, "read-only paths")
        namespaces = "-r" if self._policy.network else "-rn"
        prologue = private_mounts(
            (self._workspace, *self._readonly), mount=self._mount, mkdir=self._mkdir
        )
        script = launcher_script(
            self._bash, rlimit_values(self._policy), status_fd=status_fd, prologue=prologue
        )
        argv = (
            self._unshare,
            namespaces,
            "--pid",
            "--fork",
            "--kill-child",
            "--mount-proc",
            self._bash,
            "-c",
            script,
            LAUNCHER_ARG0,
            cmd,
        )
        fds = () if status_fd is None else (status_fd,)
        return Launch(argv=argv, env=self._env, cwd=cwd, pass_fds=fds)


def probe_unshare(unshare: str = "unshare") -> BackendProbe:
    """Check that unshare can create the namespaces and private mounts here."""
    try:
        with tempfile.TemporaryDirectory(prefix="receipts-probe-") as tmp:
            box = UnshareSandbox(tmp, SandboxPolicy(timeout_s=30.0), unshare=unshare)
            outcome = box.run("true")
    except SandboxUnavailableError as exc:
        return BackendProbe("unshare", False, f"namespaces not permitted: {exc}")
    if outcome.exit_code != 0:
        lines = outcome.stderr.strip().splitlines()
        reason = lines[-1] if lines else f"exit code {outcome.exit_code}"
        return BackendProbe("unshare", False, f"namespaces not permitted: {reason}")
    detail = f"{box.executable} (process limit: {box.process_limit}; writes NOT confined)"
    return BackendProbe("unshare", True, detail)
