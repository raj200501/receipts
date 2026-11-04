"""What every backend shares: policy checks, ``cwd`` resolution, rlimits, and ``run``.

A backend subclasses :class:`ProcessSandbox` and implements :meth:`ProcessSandbox.launch`,
which turns one command into a host command line. :meth:`ProcessSandbox.run` does the
rest: it checks ``cwd`` (relative to the workspace, never escaping it), runs the launch
through :func:`receipts.sandbox.process.run_launch`, and builds the
:class:`~receipts.sandbox.api.CommandOutcome`.

Commands always run as ``bash -c -- <cmd>``. Backends that start a new PID namespace
(bubblewrap, unshare, Docker) wrap that in a short launcher script (see
:func:`launcher_script`): it applies the policy's rlimits and then runs the command as
a child, so the command is never PID 1 of its namespace (PID 1 ignores signals it has
no handler for, which would change how ``kill`` and test suites behave).

Telling a sandbox failure from a command failure: just before it runs the command,
the launcher reports :data:`STARTED` on a status channel the command cannot reach (a
pipe whose write end the launcher closes first, or for Docker the start of the
client's stdout). When a launch ends without that report and without a timeout (for
example bubblewrap could not set up a mount, or the Docker daemon refused the
container), :meth:`ProcessSandbox.run` raises
:class:`~receipts.sandbox.api.SandboxUnavailableError` instead of returning an outcome,
so a broken sandbox is never recorded as the command's own exit status.

Backends that run as host processes with a PID namespace (bubblewrap and unshare) also
enforce ``max_procs`` with a per-command pids cgroup when one is available
(:mod:`receipts.sandbox.cgroup`), since the kernel does not apply ``ulimit -u`` to the
host's root user.
"""

from __future__ import annotations

import contextlib
import fcntl
import math
import os
import re
import resource
import shlex
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import ClassVar, Literal

from receipts.sandbox.api import CommandOutcome, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.cgroup import PidsCgroup, pids_cgroup_parent
from receipts.sandbox.env import DEFAULT_PATH, clean_env
from receipts.sandbox.process import (
    DEFAULT_MAX_CAPTURE_BYTES,
    MIN_OUTPUT_CHARS,
    Launch,
    RawResult,
    not_run,
    run_launch,
    to_outcome,
)

#: ``$0`` of the launcher script (it shows up in process listings).
LAUNCHER_ARG0 = "receipts-sandbox"

#: Exit code of the launcher when the kernel refused the policy's rlimits.
LIMITS_FAILED_EXIT_CODE = 125

#: Exit code of the launcher when a setup step before the command failed.
SETUP_FAILED_EXIT_CODE = 125

#: Status the launcher reports just before it runs the command.
STARTED = "receipts-sandbox-started"

#: Status the launcher reports when a setup step (such as a mount) failed.
SETUP_FAILED = "receipts-sandbox-setup-failed"

#: Status the launcher reports when the kernel refused the policy's rlimits.
LIMITS_FAILED = "receipts-sandbox-limits-failed"

#: Longest command, in UTF-8 bytes, that fits in one argument of ``execve``: Linux
#: limits each argument to 32 pages (``MAX_ARG_STRLEN``), terminating NUL included.
MAX_COMMAND_BYTES = 32 * os.sysconf("SC_PAGE_SIZE") - 1

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Variables bash maintains itself; the launcher keeps them so every backend matches.
SHELL_MANAGED_NAMES: frozenset[str] = frozenset({"PWD", "OLDPWD", "SHLVL"})

#: How a backend's launcher reports that the command started: through a status pipe
#: (``"fd"``), at the start of stdout (``"stdout"``), or not at all (``""``).
StartReport = Literal["fd", "stdout", ""]


class CwdError(ValueError):
    """Raised when ``cwd`` is absolute, escapes the workspace, or is not a directory."""


@dataclass(frozen=True)
class BackendProbe:
    """Whether one backend works on this machine.

    Attributes:
        name: ``"docker"``, ``"bwrap"``, or ``"unshare"``.
        ok: The backend ran a trivial command (or, for Docker, the daemon answered and
            the image is cached).
        detail: The executable used, or why the backend does not work.
    """

    name: str
    ok: bool
    detail: str


def validate_policy(policy: SandboxPolicy) -> None:
    """Raise ValueError unless every limit in ``policy`` is positive and finite.

    ``max_output_chars`` must be at least :data:`~receipts.sandbox.process.MIN_OUTPUT_CHARS`,
    since the cap keeps a head and a tail of half the limit each.
    """
    if not (math.isfinite(policy.timeout_s) and policy.timeout_s > 0):
        raise ValueError(f"timeout_s must be positive, got {policy.timeout_s!r}")
    for name in ("memory_mb", "cpu_s", "max_procs", "max_output_chars"):
        value = getattr(policy, name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if policy.max_output_chars < MIN_OUTPUT_CHARS:
        raise ValueError(
            f"max_output_chars must be at least {MIN_OUTPUT_CHARS}, got {policy.max_output_chars!r}"
        )


def check_workspace(workspace: str | Path) -> Path:
    """Return the resolved workspace path, or raise ValueError if it is not a directory."""
    path = Path(workspace).resolve()
    if not path.is_dir():
        raise ValueError(f"workspace is not a directory: {path}")
    if path == Path(path.anchor):
        raise ValueError("the filesystem root cannot be a workspace")
    return path


def check_readonly_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Resolve each read-only path, dropping duplicates; raise ValueError if one is missing."""
    resolved: dict[Path, None] = {}
    for path in paths:
        real = Path(path).resolve()
        if not real.exists():
            raise ValueError(f"read-only path does not exist: {path}")
        resolved[real] = None
    return tuple(resolved)


def require_paths(paths: Iterable[Path], what: str) -> None:
    """Raise SandboxUnavailableError if a path checked at construction is gone now.

    Backends call this before each launch: a read-only path that disappeared (for
    example a toolchain being rebuilt) breaks the sandbox, not the command.
    """
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise SandboxUnavailableError(f"{what} no longer exist: {', '.join(missing)}")


def resolve_cwd(workspace: Path, cwd: str) -> tuple[Path, str]:
    """Map ``cwd`` to ``(host directory, normalized relative POSIX path)``.

    ``cwd`` is relative to the (already resolved) ``workspace``. Symlinks are followed,
    and the result must still be inside the workspace.

    Raises:
        CwdError: ``cwd`` is absolute, holds a NUL byte, escapes the workspace, or is
            not an existing directory.
    """
    if "\0" in cwd:
        raise CwdError("cwd may not hold a NUL byte")
    pure = PurePosixPath(cwd)
    if pure.is_absolute():
        raise CwdError(f"cwd must be relative to the workspace: {cwd!r}")
    candidate = (workspace / pure).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise CwdError(f"cwd escapes the workspace: {cwd!r}")
    if not candidate.is_dir():
        raise CwdError(f"cwd is not a directory in the workspace: {cwd!r}")
    return candidate, candidate.relative_to(workspace).as_posix()


def command_problem(cmd: str) -> str | None:
    """Why ``cmd`` cannot be passed to ``bash -c`` as one argument, or None if it can.

    A command line cannot carry a NUL byte or text that is not valid Unicode (an
    unpaired surrogate, which has no UTF-8 encoding), and the kernel refuses an
    argument longer than :data:`MAX_COMMAND_BYTES` with E2BIG.
    """
    if "\0" in cmd:
        return "it holds a NUL byte, which no command line can carry"
    try:
        size = len(cmd.encode("utf-8"))
    except UnicodeEncodeError:
        return "it is not valid Unicode text (it holds an unpaired surrogate)"
    if size > MAX_COMMAND_BYTES:
        return (
            f"it is {size} bytes long, over the kernel's limit of {MAX_COMMAND_BYTES} "
            "bytes for one argument (Argument list too long)"
        )
    return None


def _stdin_problem(stdin: str | None) -> str | None:
    if stdin is None:
        return None
    try:
        stdin.encode("utf-8")
    except UnicodeEncodeError:
        return "its standard input is not valid Unicode text (it holds an unpaired surrogate)"
    return None


def find_executable(name: str, what: str) -> str:
    """Return the absolute path of executable ``name``, or raise SandboxUnavailableError."""
    found = shutil.which(name)
    if found is None:
        raise SandboxUnavailableError(f"{what} not found: {name!r}")
    return str(Path(found).absolute())


def _clamp(value: int, hard: int, scale: int) -> int:
    """``value`` limited to the current hard limit (``hard`` in kernel units / ``scale``)."""
    if hard == resource.RLIM_INFINITY or hard < 0:
        return value
    return min(value, hard // scale)


def rlimit_values(policy: SandboxPolicy) -> dict[str, int]:
    """The ``ulimit`` flags and values that enforce ``policy``.

    ``-v`` is the address space in KiB, ``-t`` CPU seconds, ``-u`` processes. Each value
    is lowered to the current hard limit when that is smaller, because only root may
    raise a hard limit. The kernel does not apply the process limit to the host root
    user, and before Linux 5.14 it counts every process of the user, not only the
    sandbox's; :class:`ProcessSandbox` adds a pids cgroup where it can.
    """
    return {
        "v": _clamp(policy.memory_mb * 1024, resource.getrlimit(resource.RLIMIT_AS)[1], 1024),
        "t": _clamp(policy.cpu_s, resource.getrlimit(resource.RLIMIT_CPU)[1], 1),
        "u": _clamp(policy.max_procs, resource.getrlimit(resource.RLIMIT_NPROC)[1], 1),
    }


def _report(status_fd: int | None, status: str, code: int) -> str:
    """Shell text that reports ``status`` (when there is a status channel) and exits."""
    if status_fd is None:
        return f"exit {code}"
    return f"{{ printf '%s\\n' {status} >&{status_fd}; exit {code}; }}"


def launcher_script(
    bash: str,
    limits: dict[str, int] | None = None,
    keep: Iterable[str] | None = None,
    *,
    status_fd: int | None = None,
    prologue: Sequence[str] = (),
) -> str:
    """The bash script that applies ``limits`` and runs ``$1`` with ``bash -c --``.

    In order, the script:

    1. with ``keep``, unsets every exported variable not named in it (or in
       :data:`SHELL_MANAGED_NAMES`), since a container image may define its own;
    2. runs each ``prologue`` line (setup steps such as mounts); if one fails it
       reports :data:`SETUP_FAILED` and exits with :data:`SETUP_FAILED_EXIT_CODE`;
    3. applies ``limits``; if the kernel refuses one it reports :data:`LIMITS_FAILED`
       and exits with :data:`LIMITS_FAILED_EXIT_CODE` before running anything;
    4. with ``status_fd``, writes :data:`STARTED` to that descriptor and, unless it is
       stdout or stderr, closes it, so the command never holds it;
    5. runs the command as a child (never PID 1) and passes its exit status through.

    The launcher's own stderr is discarded once the limits are set, so its job notices
    (such as ``Killed``) never mix with the command's stderr, which goes to the
    original stream.

    Raises:
        ValueError: A name in ``keep`` is not a shell identifier, or ``status_fd`` is
            negative.
    """
    if status_fd is not None and status_fd < 0:
        raise ValueError(f"status_fd may not be negative, got {status_fd!r}")
    lines = []
    if keep is not None:
        names = sorted(set(keep) | SHELL_MANAGED_NAMES)
        bad = [n for n in names if not _IDENTIFIER.fullmatch(n)]
        if bad:
            raise ValueError(f"not shell identifiers: {', '.join(bad)}")
        pattern = "|".join(names)
        lines.append(
            "for _receipts_v in $(compgen -e); do case $_receipts_v in "
            f'{pattern}) ;; *) unset "$_receipts_v" ;; esac; done; unset _receipts_v'
        )
    for step in prologue:
        lines.append(f"{{ {step}; }} || {_report(status_fd, SETUP_FAILED, SETUP_FAILED_EXIT_CODE)}")
    if limits:
        sets = " && ".join(f"ulimit -S -H -{flag} {value}" for flag, value in limits.items())
        lines.append(f"{sets} || {_report(status_fd, LIMITS_FAILED, LIMITS_FAILED_EXIT_CODE)}")
    if status_fd is not None:
        lines.append(f"printf '%s\\n' {STARTED} >&{status_fd}")
        if status_fd > 2:
            lines.append(f"exec {status_fd}>&-")
    lines.append("exec 3>&2 2>/dev/null")
    lines.append(f'{shlex.quote(bash)} -c -- "$1" bash 2>&3 3>&-')
    lines.append("exit $?")
    return "\n".join(lines)


def _high_fd(fd: int) -> int:
    """``fd`` moved to a number above 2 (close-on-exec), so it never shadows a std stream."""
    if fd > 2:
        return fd
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
    os.close(fd)
    return moved


class StatusChannel:
    """A pipe the launcher reports through (see :func:`launcher_script`).

    Use it as a context manager; pass :attr:`write_fd` to the launch (it is inherited
    through ``pass_fds``) and call :meth:`read` once the host process is gone.
    """

    def __init__(self) -> None:
        self._read_fd = -1
        self._write_fd = -1

    def __enter__(self) -> StatusChannel:
        """Open the pipe (both ends above descriptor 2, the read end non-blocking)."""
        read_fd, write_fd = os.pipe()
        self._read_fd, self._write_fd = _high_fd(read_fd), _high_fd(write_fd)
        os.set_blocking(self._read_fd, False)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close both ends."""
        self._close_write()
        if self._read_fd >= 0:
            os.close(self._read_fd)
            self._read_fd = -1

    @property
    def write_fd(self) -> int:
        """The descriptor the launcher writes to."""
        return self._write_fd

    def _close_write(self) -> None:
        if self._write_fd >= 0:
            os.close(self._write_fd)
            self._write_fd = -1

    def read(self, limit: int = 65536) -> str:
        """Close this process's write end and return what the launcher reported."""
        self._close_write()
        data = b""
        with contextlib.suppress(BlockingIOError):
            while len(data) < limit:
                chunk = os.read(self._read_fd, limit - len(data))
                if not chunk:
                    break
                data += chunk
        return data.decode("utf-8", errors="replace")


class ProcessSandbox(ABC):
    """Base class for backends that start one host process per command.

    Args:
        workspace: The workspace directory (resolved; it must exist).
        policy: Limits and allowances; the defaults of :class:`SandboxPolicy` if None.
        max_capture_bytes: Each of stdout and stderr may grow to this many bytes
            before the command is stopped, and only this many bytes of each are kept
            (the outcome is still capped at ``policy.max_output_chars``).

    Raises:
        ValueError: The workspace is not a directory, a policy limit is not positive,
            or ``policy.env`` is refused by :func:`receipts.sandbox.env.clean_env`.
    """

    #: The backend name reported in every outcome.
    backend_name: ClassVar[str] = ""
    #: Whether writes outside the workspace are blocked.
    confines_writes: ClassVar[bool] = True
    #: How the backend's launcher reports that the command started.
    start_report: ClassVar[StartReport] = ""
    #: Whether ``max_procs`` is enforced with a per-command pids cgroup when possible.
    uses_pids_cgroup: ClassVar[bool] = False

    def __init__(
        self,
        workspace: str | Path,
        policy: SandboxPolicy | None = None,
        *,
        max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    ) -> None:
        self._workspace = check_workspace(workspace)
        self._policy = policy if policy is not None else SandboxPolicy()
        validate_policy(self._policy)
        if max_capture_bytes <= 0:
            raise ValueError(f"max_capture_bytes must be positive, got {max_capture_bytes!r}")
        self._max_capture_bytes = max_capture_bytes
        self._env = clean_env(self._workspace, self._policy, DEFAULT_PATH)
        self._pids_parent = pids_cgroup_parent() if self.uses_pids_cgroup else None

    @property
    def backend(self) -> str:
        """The backend name (``"docker"``, ``"bwrap"``, ``"unshare"``, or ``"fake"``)."""
        return self.backend_name

    @property
    def workspace(self) -> Path:
        """Host path of the workspace root."""
        return self._workspace

    @property
    def policy(self) -> SandboxPolicy:
        """The policy every command runs under."""
        return self._policy

    @property
    def env(self) -> dict[str, str]:
        """A copy of the environment every command starts with."""
        return dict(self._env)

    @property
    def process_limit(self) -> str:
        """How ``policy.max_procs`` is enforced here.

        ``"cgroup"`` (a per-command pids cgroup), ``"rlimit"`` (``ulimit -u`` alone,
        which binds a user other than root), or ``"none"`` (this backend applies no
        process limit, or it runs as the host's root user and no pids cgroup is
        available). Backends with their own mechanism override this.
        """
        if self._pids_parent is not None:
            return "cgroup"
        if self.uses_pids_cgroup and os.geteuid() != 0:
            return "rlimit"
        return "none"

    @abstractmethod
    def launch(
        self, cmd: str, cwd: Path, *, interactive: bool = False, status_fd: int | None = None
    ) -> Launch:
        """Return the host command line that runs ``cmd`` in host directory ``cwd``.

        ``interactive`` is True when the command gets standard input. ``status_fd`` is
        the status pipe's write end for backends whose ``start_report`` is ``"fd"``.

        Raises:
            SandboxUnavailableError: The sandbox cannot be set up any more (for
                example a read-only path is gone).
        """

    def run(
        self, cmd: str, *, cwd: str = ".", timeout_s: float | None = None, stdin: str | None = None
    ) -> CommandOutcome:
        """Run ``cmd`` with ``bash -c`` in ``cwd`` (relative to the workspace).

        A command that no command line can carry (see :func:`command_problem`), or
        standard input that is not valid Unicode text, is not started: the outcome has
        exit code :data:`~receipts.sandbox.process.CANNOT_RUN_EXIT_CODE` and the
        reason on stderr, as a shell reports a command it cannot execute. Such text
        usually comes from an agent, so it is reported, not raised.

        Args:
            cmd: The shell command.
            cwd: Working directory relative to the workspace root.
            timeout_s: Wall-clock limit; ``policy.timeout_s`` if None.
            stdin: Text for standard input; None gives ``/dev/null``.

        Raises:
            CwdError: ``cwd`` is absolute, escapes the workspace, or is not a directory.
            ValueError: ``timeout_s`` is not positive.
            SandboxUnavailableError: The sandbox itself failed before the command
                started (see the module docstring), so there is no outcome to report.
            OSError: The backend's host process could not be started.
        """
        limit = self._policy.timeout_s if timeout_s is None else timeout_s
        if not (math.isfinite(limit) and limit > 0):
            raise ValueError(f"timeout_s must be positive, got {limit!r}")
        host_cwd, rel_cwd = resolve_cwd(self._workspace, cwd)
        problem = command_problem(cmd) or _stdin_problem(stdin)
        if problem is not None:
            raw = not_run(problem, max_output_chars=self._policy.max_output_chars)
        else:
            raw = self._execute(cmd, host_cwd, limit, stdin)
        return to_outcome(
            raw,
            cmd=cmd,
            cwd=rel_cwd,
            backend=self.backend,
            max_capture_bytes=self._max_capture_bytes,
        )

    def _execute(self, cmd: str, host_cwd: Path, timeout_s: float, stdin: str | None) -> RawResult:
        """Launch ``cmd`` (in a pids cgroup when there is one) and check that it started."""
        with contextlib.ExitStack() as stack:
            channel = stack.enter_context(StatusChannel()) if self.start_report == "fd" else None
            launch = self.launch(
                cmd,
                host_cwd,
                interactive=stdin is not None,
                status_fd=channel.write_fd if channel is not None else None,
            )
            if self._pids_parent is not None:
                bash = find_executable("bash", "bash")
                cgroup = stack.enter_context(
                    PidsCgroup(self._pids_parent, self._policy.max_procs, bash)
                )
                launch = cgroup.wrap(launch)
            raw = run_launch(
                launch,
                timeout_s=timeout_s,
                stdin=stdin,
                max_capture_bytes=self._max_capture_bytes,
                max_output_chars=self._policy.max_output_chars,
            )
            status = channel.read() if channel is not None else ""
        self._check_started(raw, status)
        return raw

    def _check_started(self, raw: RawResult, status: str) -> None:
        """Raise SandboxUnavailableError when the launcher never started the command."""
        if not self.start_report or raw.timed_out:
            return
        reported = status.split()
        started = raw.marker_seen if self.start_report == "stdout" else STARTED in reported
        if started:
            return
        lines = raw.stderr.text.strip().splitlines()
        detail = f"exit code {raw.exit_code}" + (f": {lines[-1]}" if lines else "")
        if LIMITS_FAILED in reported:
            raise SandboxUnavailableError(
                f"{self.backend}: the kernel refused the sandbox's limits ({detail})"
            )
        if SETUP_FAILED in reported:
            raise SandboxUnavailableError(f"{self.backend}: the sandbox setup failed ({detail})")
        raise SandboxUnavailableError(
            f"{self.backend}: the sandbox did not start the command ({detail})"
        )
