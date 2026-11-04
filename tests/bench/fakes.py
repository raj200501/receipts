"""A subprocess-backed fake Sandbox for the bench tests.

It runs ``bash -c`` in the workspace with a small allowlisted environment (like
the real backends) and, when ``unshare -rn`` works on this machine, inside a new
network namespace so nothing can reach the network. It confines nothing else, so
the bench tests use it only for this repository's own task files and for the
synthetic tasks they write themselves.
"""

from __future__ import annotations

import functools
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from receipts.ledger.events import cap_stream
from receipts.sandbox.api import CommandOutcome


@functools.cache
def _unshare_works() -> bool:
    exe = shutil.which("unshare")
    if exe is None:
        return False
    try:
        probe = subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def toolchain_path() -> str:
    """PATH for sandboxed commands: this interpreter's bin (python3 with pytest), node, system."""
    dirs = [str(Path(sys.executable).parent)]
    node = shutil.which("node")
    if node:
        dirs.append(str(Path(node).resolve().parent))
    dirs += ["/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dict.fromkeys(dirs))


class SubprocessSandbox:
    """Test-only :class:`receipts.sandbox.api.Sandbox` (backend ``"fake"``).

    Args:
        workspace: The workspace root.
        isolate_network: Use ``unshare -rn`` when it works here.
    """

    def __init__(self, workspace: Path, *, isolate_network: bool = True) -> None:
        self._workspace = workspace
        self._isolate = isolate_network and _unshare_works()
        self.commands: list[str] = []

    @property
    def backend(self) -> str:
        """Always ``"fake"``."""
        return "fake"

    @property
    def workspace(self) -> Path:
        """The workspace root."""
        return self._workspace

    def run(
        self, cmd: str, *, cwd: str = ".", timeout_s: float | None = None, stdin: str | None = None
    ) -> CommandOutcome:
        """Run ``cmd`` with ``bash -c`` in ``cwd`` under the workspace."""
        self.commands.append(cmd)
        env = {
            "PATH": toolchain_path(),
            "HOME": str(self._workspace),
            "LANG": "C.UTF-8",
            "TERM": "dumb",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "npm_config_update_notifier": "false",
        }
        argv = ["bash", "-c", cmd]
        if self._isolate:
            argv = ["unshare", "-rn", *argv]
        start = time.monotonic()
        proc = subprocess.Popen(
            argv,
            cwd=self._workspace / cwd,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(input=stdin, timeout=timeout_s or 120.0)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
            timed_out = True
        code = -9 if timed_out else proc.returncode
        out, out_cut, out_sha = cap_stream(stdout)
        err, err_cut, err_sha = cap_stream(stderr)
        return CommandOutcome(
            cmd=cmd,
            cwd=cwd,
            exit_code=code,
            stdout=out,
            stderr=err,
            duration_s=time.monotonic() - start,
            timed_out=timed_out,
            stdout_truncated=out_cut,
            stderr_truncated=err_cut,
            stdout_sha256=out_sha,
            stderr_sha256=err_sha,
            backend="fake",
        )


def factory(*, isolate_network: bool = True) -> Callable[[Path], SubprocessSandbox]:
    """A ``sandbox_factory`` for :func:`receipts.bench.validate.validate_task`."""

    def make(workspace: Path) -> SubprocessSandbox:
        return SubprocessSandbox(workspace, isolate_network=isolate_network)

    return make
