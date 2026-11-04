"""Start one host process, capture its streams, and stop it on timeout.

Every backend reduces a command to a :class:`Launch` (the host command line that runs
it inside the sandbox) and hands it to :func:`run_launch`, which:

- captures stdout and stderr through anonymous temporary files outside the workspace
  (no pipes, so a command that floods its output or leaves a background process
  holding a stream can never block the caller);
- starts the process in a new session, so it leads its own process group;
- waits for it without reaping it, then kills its whole process group, so no
  straggler outlives the call and the group ID cannot be reused in between;
- on timeout, runs the launch's ``stop`` step (removing the container, for Docker),
  kills the process group, runs ``stop`` once more after the host process is gone
  (a container the daemon created in between is removed too), and reports exit
  code 124;
- stops a command whose stdout or stderr passes ``max_capture_bytes``, so a runaway
  command cannot fill the host disk (the same steps as a timeout);
- runs the same steps when waiting is interrupted (for example by
  ``KeyboardInterrupt``) before the exception propagates.

:func:`to_outcome` then decodes the streams as UTF-8 (invalid bytes replaced), caps
each with :func:`receipts.ledger.events.cap_stream` (head and tail kept), and records
the SHA-256 of each full stream.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from receipts.ledger.events import cap_stream
from receipts.sandbox.api import CommandOutcome

#: Exit code reported when the wall-clock limit stopped a command (as GNU ``timeout``).
TIMEOUT_EXIT_CODE = 124

#: Exit code reported for a command that could not be started at all (as a shell
#: reports a command it cannot execute, for example "Argument list too long").
CANNOT_RUN_EXIT_CODE = 126

#: Default ceiling on each captured stream, in bytes, before the command is stopped.
DEFAULT_MAX_CAPTURE_BYTES = 64 * 1024 * 1024

_POLL_MIN_S = 0.001
_POLL_MAX_S = 0.05


@dataclass(frozen=True)
class Launch:
    """How to start one sandboxed command on the host.

    Attributes:
        argv: The host command line (absolute executable first).
        env: The environment of the host process.
        cwd: The host working directory of the host process.
        stop: Optional extra step for a command that is stopped (timeout, output
            overflow, or an interrupted wait): it runs once before the process group
            is killed and once after the host process is gone, so it must be
            idempotent and must not raise (for example ``docker rm --force`` of the
            container).
    """

    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path
    stop: Callable[[], None] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class RawResult:
    """What one host process did, before decoding and capping.

    Attributes:
        exit_code: Shell-style status: the exit code, ``128 + n`` after signal ``n``,
            or :data:`TIMEOUT_EXIT_CODE` after a timeout.
        stdout: Every byte written to stdout.
        stderr: Every byte written to stderr.
        duration_s: Wall-clock time from start until the process was gone.
        timed_out: The wall-clock limit stopped the process.
        overflow: ``"stdout"`` or ``"stderr"`` when that stream passed the capture
            ceiling and the process was stopped for it, else None.
    """

    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_s: float
    timed_out: bool
    overflow: str | None


def exit_status(returncode: int, timed_out: bool) -> int:
    """Map a ``subprocess`` return code to a shell-style exit status."""
    if timed_out:
        return TIMEOUT_EXIT_CODE
    if returncode < 0:
        return 128 - returncode
    return returncode


def _has_exited(pid: int) -> bool:
    """True once ``pid`` has exited; it is left unreaped, so its group ID stays reserved."""
    try:
        state = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return True
    return state is not None


def _kill_group(pgid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def _size(handle: IO[bytes]) -> int:
    return os.fstat(handle.fileno()).st_size


def _wait(
    pid: int, deadline: float, streams: tuple[tuple[str, IO[bytes]], ...], limit: int
) -> tuple[bool, str | None]:
    """Wait for exit, the deadline, or a stream past ``limit``: ``(timed_out, overflow)``."""
    delay = _POLL_MIN_S
    while not _has_exited(pid):
        for label, handle in streams:
            if _size(handle) > limit:
                return False, label
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True, None
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, _POLL_MAX_S)
    return False, None


def run_launch(
    launch: Launch,
    *,
    timeout_s: float,
    stdin: str | None = None,
    max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
) -> RawResult:
    """Run ``launch`` to completion, or stop it, and return what it did.

    Args:
        launch: The host command line and its environment.
        timeout_s: Wall-clock limit in seconds.
        stdin: Text for the process's standard input (UTF-8); None gives it
            ``/dev/null``.
        max_capture_bytes: Ceiling on each captured stream before the process is
            stopped.

    Raises:
        ValueError: ``timeout_s`` or ``max_capture_bytes`` is not positive.
        OSError: The host process could not be started.
    """
    if not timeout_s > 0:
        raise ValueError(f"timeout_s must be positive, got {timeout_s!r}")
    if max_capture_bytes <= 0:
        raise ValueError(f"max_capture_bytes must be positive, got {max_capture_bytes!r}")
    with contextlib.ExitStack() as stack:
        out = stack.enter_context(tempfile.TemporaryFile(prefix="receipts-stdout-"))
        err = stack.enter_context(tempfile.TemporaryFile(prefix="receipts-stderr-"))
        source: int | IO[bytes] = subprocess.DEVNULL
        if stdin is not None:
            source = stack.enter_context(tempfile.TemporaryFile(prefix="receipts-stdin-"))
            source.write(stdin.encode("utf-8"))
            source.flush()
            source.seek(0)
        start = time.monotonic()
        proc = subprocess.Popen(
            list(launch.argv),
            stdin=source,
            stdout=out,
            stderr=err,
            cwd=launch.cwd,
            env=dict(launch.env),
            start_new_session=True,
        )
        timed_out, overflow = False, None
        stopped = True  # until the wait reports that the process exited by itself
        try:
            timed_out, overflow = _wait(
                proc.pid,
                start + timeout_s,
                (("stdout", out), ("stderr", err)),
                max_capture_bytes,
            )
            stopped = timed_out or overflow is not None
        finally:
            if stopped and launch.stop is not None:
                launch.stop()
            _kill_group(proc.pid)
            returncode = proc.wait()
            if stopped and launch.stop is not None:
                launch.stop()
        duration = time.monotonic() - start
        out.seek(0)
        err.seek(0)
        return RawResult(
            exit_code=exit_status(returncode, timed_out),
            stdout=out.read(),
            stderr=err.read(),
            duration_s=duration,
            timed_out=timed_out,
            overflow=overflow,
        )


def not_run(reason: str) -> RawResult:
    """The result for a command that was never started, with ``reason`` on stderr.

    The exit code is :data:`CANNOT_RUN_EXIT_CODE`, stdout is empty, and stderr is one
    line starting ``receipts: the command was not run:`` (so it cannot be mistaken
    for output of the command).
    """
    message = f"receipts: the command was not run: {reason}\n"
    return RawResult(
        exit_code=CANNOT_RUN_EXIT_CODE,
        stdout=b"",
        stderr=message.encode("utf-8"),
        duration_s=0.0,
        timed_out=False,
        overflow=None,
    )


def overflow_note(stream: str, max_capture_bytes: int) -> str:
    """The line appended to stderr when a command was stopped for flooding ``stream``."""
    return (
        f"\n[receipts: the command was stopped because its {stream} passed "
        f"{max_capture_bytes} bytes]\n"
    )


def to_outcome(
    raw: RawResult,
    *,
    cmd: str,
    cwd: str,
    backend: str,
    max_output_chars: int,
    max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
) -> CommandOutcome:
    """Decode, cap, and hash ``raw``'s streams into a :class:`CommandOutcome`.

    Each stream is decoded as UTF-8 with invalid bytes replaced, then capped at
    ``max_output_chars`` (head and tail kept); the hash covers the whole decoded
    stream. When the command was stopped for output volume, :func:`overflow_note`
    is appended to the capped stderr (the hash still covers only what the command
    wrote).
    """
    stdout, stdout_cut, stdout_sha = cap_stream(
        raw.stdout.decode("utf-8", errors="replace"), max_output_chars
    )
    stderr, stderr_cut, stderr_sha = cap_stream(
        raw.stderr.decode("utf-8", errors="replace"), max_output_chars
    )
    if raw.overflow is not None:
        stderr += overflow_note(raw.overflow, max_capture_bytes)
    return CommandOutcome(
        cmd=cmd,
        cwd=cwd,
        exit_code=raw.exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_s=raw.duration_s,
        timed_out=raw.timed_out,
        stdout_truncated=stdout_cut,
        stderr_truncated=stderr_cut,
        stdout_sha256=stdout_sha,
        stderr_sha256=stderr_sha,
        backend=backend,
    )
