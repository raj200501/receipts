"""UnshareSandbox: ``unshare -rn`` network isolation only. IT DOES NOT CONFINE WRITES.

WARNING: a command in this sandbox can read and write anything the invoking user can,
anywhere on the host, and can reach host Unix sockets (for example the Docker
daemon's). It only removes network access (a new, empty network namespace), starts
from the clean environment, and applies rlimits. Per DECISIONS D5 it may run only this
project's own generated tasks: never subject agents on third-party task repositories,
graders, or benchmark scripts. Prefer :class:`~receipts.sandbox.bwrap.BwrapSandbox` or
:class:`~receipts.sandbox.docker.DockerSandbox` whenever either works.

Each command runs as ``unshare -rn --pid --fork --kill-child --mount-proc``: user and
network namespaces as in D5, plus a PID namespace that ties every process the command
starts to the launcher, so a timeout kills them all (including ones that start their
own session). ``--mount-proc`` gives that PID namespace its own ``/proc`` (inside a
private mount namespace that holds nothing else), so ``/proc/<pid>`` matches the PIDs
the command sees. None of this confines writes.

As under bubblewrap, the kernel does not enforce the process limit (``max_procs``)
for processes of the host's root user, so started by root a command can start any
number of processes until the timeout ends it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

from receipts.sandbox.api import SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    LAUNCHER_ARG0,
    BackendProbe,
    ProcessSandbox,
    find_executable,
    launcher_script,
    rlimit_values,
)
from receipts.sandbox.process import DEFAULT_MAX_CAPTURE_BYTES, Launch


class UnshareSandbox(ProcessSandbox):
    """Network-isolated commands that are NOT write-confined (see the module warning).

    Args:
        workspace: The workspace directory (commands start there, but may write
            anywhere the invoking user can).
        policy: Limits and allowances; :class:`SandboxPolicy` defaults if None.
            ``readonly_paths`` need no mounts: the whole host is visible.
        unshare: The util-linux ``unshare`` executable.
        max_capture_bytes: Stream ceiling before the command is stopped.

    Raises:
        SandboxUnavailableError: ``unshare`` or bash is not installed.
        ValueError: The workspace or the policy is invalid.
    """

    backend_name: ClassVar[str] = "unshare"
    confines_writes: ClassVar[bool] = False

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
        self._bash = find_executable("bash", "bash")

    @property
    def executable(self) -> str:
        """The unshare executable in use."""
        return self._unshare

    def launch(self, cmd: str, cwd: Path, *, interactive: bool = False) -> Launch:
        """The unshare command line for ``cmd``, started in host directory ``cwd``."""
        namespaces = "-r" if self._policy.network else "-rn"
        script = launcher_script(self._bash, rlimit_values(self._policy))
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
        return Launch(argv=argv, env=self._env, cwd=cwd)


def probe_unshare(unshare: str = "unshare") -> BackendProbe:
    """Check that unshare can create the user, network, and PID namespaces here."""
    try:
        with tempfile.TemporaryDirectory(prefix="receipts-probe-") as tmp:
            box = UnshareSandbox(tmp, SandboxPolicy(timeout_s=30.0), unshare=unshare)
            outcome = box.run("true")
    except SandboxUnavailableError as exc:
        return BackendProbe("unshare", False, str(exc))
    if outcome.exit_code != 0:
        lines = outcome.stderr.strip().splitlines()
        reason = lines[-1] if lines else f"exit code {outcome.exit_code}"
        return BackendProbe("unshare", False, f"namespaces not permitted: {reason}")
    return BackendProbe("unshare", True, box.executable)
