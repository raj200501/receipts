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
"""

from __future__ import annotations

import math
import os
import re
import resource
import shlex
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar

from receipts.sandbox.api import CommandOutcome, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.env import DEFAULT_PATH, clean_env
from receipts.sandbox.process import (
    DEFAULT_MAX_CAPTURE_BYTES,
    Launch,
    not_run,
    run_launch,
    to_outcome,
)

#: ``$0`` of the launcher script (it shows up in process listings).
LAUNCHER_ARG0 = "receipts-sandbox"

#: Exit code of the launcher when the kernel refused the policy's rlimits.
LIMITS_FAILED_EXIT_CODE = 125

#: Longest command, in UTF-8 bytes, that fits in one argument of ``execve``: Linux
#: limits each argument to 32 pages (``MAX_ARG_STRLEN``), terminating NUL included.
MAX_COMMAND_BYTES = 32 * os.sysconf("SC_PAGE_SIZE") - 1

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Variables bash maintains itself; the launcher keeps them so every backend matches.
SHELL_MANAGED_NAMES: frozenset[str] = frozenset({"PWD", "OLDPWD", "SHLVL"})


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
    """Raise ValueError unless every limit in ``policy`` is positive and finite."""
    if not (math.isfinite(policy.timeout_s) and policy.timeout_s > 0):
        raise ValueError(f"timeout_s must be positive, got {policy.timeout_s!r}")
    for name in ("memory_mb", "cpu_s", "max_procs", "max_output_chars"):
        value = getattr(policy, name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive integer, got {value!r}")


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
    sandbox's.
    """
    return {
        "v": _clamp(policy.memory_mb * 1024, resource.getrlimit(resource.RLIMIT_AS)[1], 1024),
        "t": _clamp(policy.cpu_s, resource.getrlimit(resource.RLIMIT_CPU)[1], 1),
        "u": _clamp(policy.max_procs, resource.getrlimit(resource.RLIMIT_NPROC)[1], 1),
    }


def launcher_script(
    bash: str, limits: dict[str, int] | None = None, keep: Iterable[str] | None = None
) -> str:
    """The bash script that applies ``limits`` and runs ``$1`` with ``bash -c --``.

    The command runs as a child of the launcher (never PID 1) and its exit status is
    passed through. With ``keep``, every exported variable not named in it (or in
    :data:`SHELL_MANAGED_NAMES`) is unset first, since a container image may define
    its own. The launcher's own stderr is discarded once the limits are set, so its
    job notices (such as ``Killed``) never mix with the command's stderr, which goes
    to the original stream. If the kernel refuses a limit, the launcher exits with
    :data:`LIMITS_FAILED_EXIT_CODE` before running anything.

    Raises:
        ValueError: A name in ``keep`` is not a shell identifier.
    """
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
    if limits:
        sets = " && ".join(f"ulimit -S -H -{flag} {value}" for flag, value in limits.items())
        lines.append(f"{sets} || exit {LIMITS_FAILED_EXIT_CODE}")
    lines.append("exec 3>&2 2>/dev/null")
    lines.append(f'{shlex.quote(bash)} -c -- "$1" bash 2>&3 3>&-')
    lines.append("exit $?")
    return "\n".join(lines)


class ProcessSandbox(ABC):
    """Base class for backends that start one host process per command.

    Args:
        workspace: The workspace directory (resolved; it must exist).
        policy: Limits and allowances; the defaults of :class:`SandboxPolicy` if None.
        max_capture_bytes: Each of stdout and stderr may grow to this many bytes
            before the command is stopped (the outcome is still capped at
            ``policy.max_output_chars``).

    Raises:
        ValueError: The workspace is not a directory, a policy limit is not positive,
            or ``policy.env`` is refused by :func:`receipts.sandbox.env.clean_env`.
    """

    #: The backend name reported in every outcome.
    backend_name: ClassVar[str] = ""
    #: Whether writes outside the workspace are blocked.
    confines_writes: ClassVar[bool] = True

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

    @abstractmethod
    def launch(self, cmd: str, cwd: Path, *, interactive: bool = False) -> Launch:
        """Return the host command line that runs ``cmd`` in host directory ``cwd``.

        ``interactive`` is True when the command gets standard input.
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
            OSError: The backend's host process could not be started.
        """
        limit = self._policy.timeout_s if timeout_s is None else timeout_s
        if not (math.isfinite(limit) and limit > 0):
            raise ValueError(f"timeout_s must be positive, got {limit!r}")
        host_cwd, rel_cwd = resolve_cwd(self._workspace, cwd)
        problem = command_problem(cmd) or _stdin_problem(stdin)
        if problem is not None:
            raw = not_run(problem)
        else:
            launch = self.launch(cmd, host_cwd, interactive=stdin is not None)
            raw = run_launch(
                launch, timeout_s=limit, stdin=stdin, max_capture_bytes=self._max_capture_bytes
            )
        return to_outcome(
            raw,
            cmd=cmd,
            cwd=rel_cwd,
            backend=self.backend,
            max_output_chars=self._policy.max_output_chars,
            max_capture_bytes=self._max_capture_bytes,
        )
