"""Start one host process, capture its streams, and stop it on timeout.

Every backend reduces a command to a :class:`Launch` (the host command line that runs
it inside the sandbox) and hands it to :func:`run_launch`, which:

- captures stdout and stderr through anonymous temporary files outside the workspace
  (no pipes, so a command that floods its output or leaves a background process
  holding a stream can never block the caller), and gives standard input a read-only
  descriptor (the command cannot write to, truncate, or grow it);
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

Reading the captured streams is bounded in memory and time, whatever the command did
to its output files: a command holds them open read-write, so it can ``lseek`` or
``ftruncate`` them to any size at no cost (a sparse file). After the process is gone
each file's final size is checked again, and only its first ``max_capture_bytes``
bytes are kept, even when the command exited by itself. Those bytes are read in
chunks of :data:`READ_CHUNK_BYTES`: the harness holds one chunk plus the head and tail
it keeps, never the whole stream. Each kept stream is decoded as UTF-8 (invalid bytes
replaced), capped exactly as :func:`receipts.ledger.events.cap_stream` does (head and
tail kept, the same elision marker; short streams go through ``cap_stream`` itself),
and hashed (SHA-256 of the decoded text, as ``cap_stream`` hashes). :func:`to_outcome`
then builds the :class:`~receipts.sandbox.api.CommandOutcome`, with a note on stderr
for each stream that passed the ceiling.
"""

from __future__ import annotations

import codecs
import contextlib
import hashlib
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from receipts.ledger.events import MAX_STREAM_CHARS, cap_stream
from receipts.sandbox.api import CommandOutcome

#: Exit code reported when the wall-clock limit stopped a command (as GNU ``timeout``).
TIMEOUT_EXIT_CODE = 124

#: Exit code reported for a command that could not be started at all (as a shell
#: reports a command it cannot execute, for example "Argument list too long").
CANNOT_RUN_EXIT_CODE = 126

#: Default ceiling on each captured stream, in bytes, before the command is stopped.
DEFAULT_MAX_CAPTURE_BYTES = 64 * 1024 * 1024

#: Default cap on each stream's text in an outcome (the ledger's own limit).
DEFAULT_MAX_OUTPUT_CHARS = MAX_STREAM_CHARS

#: Smallest ``max_output_chars``: the cap keeps a head and a tail of half the limit each.
MIN_OUTPUT_CHARS = 2

#: Bytes read from a capture file at a time.
READ_CHUNK_BYTES = 1024 * 1024

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
        pass_fds: Descriptors the host process inherits besides the standard streams
            (for example the write end of a status pipe).
        stdout_marker: Bytes the sandbox's launcher writes to stdout before the
            command starts. When stdout begins with them they are removed from the
            captured stream and :attr:`RawResult.marker_seen` is True.
    """

    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path
    stop: Callable[[], None] | None = field(default=None, compare=False)
    pass_fds: tuple[int, ...] = ()
    stdout_marker: bytes = b""


@dataclass(frozen=True)
class Capture:
    """One captured stream, decoded, capped, and hashed.

    Attributes:
        text: The kept bytes decoded as UTF-8 (invalid bytes replaced), capped with
            head and tail kept.
        truncated: ``text`` is not the whole stream: it was capped, or the stream
            held more than the kept bytes.
        sha256: Hex SHA-256 of the kept bytes, decoded (the hash ``cap_stream``
            reports).
        size: Bytes the stream held when the command was gone.
        kept: Bytes decoded and hashed: the first ``min(size, max_capture_bytes)``.
    """

    text: str
    truncated: bool
    sha256: str
    size: int
    kept: int


@dataclass(frozen=True)
class RawResult:
    """What one host process did, with its streams captured.

    Attributes:
        exit_code: Shell-style status: the exit code, ``128 + n`` after signal ``n``,
            or :data:`TIMEOUT_EXIT_CODE` after a timeout.
        stdout: The captured stdout (without the launch's ``stdout_marker``).
        stderr: The captured stderr.
        duration_s: Wall-clock time from start until the process was gone.
        timed_out: The wall-clock limit stopped the process.
        overflow: ``"stdout"`` or ``"stderr"`` when that stream passed the capture
            ceiling while the process ran and the process was stopped for it, else
            None. (A stream can also end over the ceiling without a stop; its
            ``size`` then exceeds its ``kept``.)
        marker_seen: stdout began with the launch's ``stdout_marker``.
    """

    exit_code: int
    stdout: Capture
    stderr: Capture
    duration_s: float
    timed_out: bool
    overflow: str | None
    marker_seen: bool = False


class _HeadTail:
    """Decoded text, kept whole up to ``max_chars`` characters, then only head and tail."""

    def __init__(self, max_chars: int) -> None:
        self._max = max_chars
        self._half = max_chars // 2
        self._pieces: list[str] = []
        self._head = ""
        self._tail = ""
        self._chars = 0
        self._whole = True
        self._digest = hashlib.sha256()

    def add(self, piece: str) -> None:
        """Append decoded text (without lone surrogates, as a UTF-8 decoder gives)."""
        if not piece:
            return
        self._digest.update(piece.encode("utf-8"))
        self._chars += len(piece)
        if self._whole:
            self._pieces.append(piece)
            if self._chars > self._max:
                text = "".join(self._pieces)
                self._pieces = []
                self._head = text[: self._half]
                self._tail = text[len(text) - self._half :]
                self._whole = False
            return
        joined = self._tail + piece
        self._tail = joined[len(joined) - self._half :]

    def result(self) -> tuple[str, bool, str]:
        """``(capped_text, truncated, sha256)``, as :func:`cap_stream` returns them."""
        if self._whole:
            return cap_stream("".join(self._pieces), self._max)
        marker = f"\n[... {self._chars - 2 * self._half} chars elided by receipts ...]\n"
        return self._head + marker + self._tail, True, self._digest.hexdigest()


def _check_output_chars(max_output_chars: int) -> None:
    if max_output_chars < MIN_OUTPUT_CHARS:
        raise ValueError(
            f"max_output_chars must be at least {MIN_OUTPUT_CHARS}, got {max_output_chars!r}"
        )


def _capture(blocks: Iterator[bytes], size: int, max_output_chars: int) -> Capture:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = _HeadTail(max_output_chars)
    kept = 0
    for block in blocks:
        kept += len(block)
        text.add(decoder.decode(block))
    text.add(decoder.decode(b"", final=True))
    capped, cut, digest = text.result()
    return Capture(text=capped, truncated=cut or size > kept, sha256=digest, size=size, kept=kept)


def read_capture(fd: int, *, max_bytes: int, max_output_chars: int, start: int = 0) -> Capture:
    """Capture the stream in file ``fd`` from offset ``start``, keeping at most ``max_bytes``.

    The file is read in chunks with ``pread`` (its offset is left alone), so memory
    stays bounded by one chunk plus the kept head and tail, whatever the file's size.

    Raises:
        ValueError: ``max_bytes`` is negative or ``max_output_chars`` is below
            :data:`MIN_OUTPUT_CHARS`.
    """
    if max_bytes < 0:
        raise ValueError(f"max_bytes may not be negative, got {max_bytes!r}")
    _check_output_chars(max_output_chars)
    size = max(os.fstat(fd).st_size - start, 0)

    def blocks() -> Iterator[bytes]:
        offset, remaining = start, min(size, max_bytes)
        while remaining > 0:
            block = os.pread(fd, min(READ_CHUNK_BYTES, remaining), offset)
            if not block:  # the file shrank while it was read
                return
            offset += len(block)
            remaining -= len(block)
            yield block

    return _capture(blocks(), size, max_output_chars)


def capture_bytes(data: bytes, *, max_output_chars: int, max_bytes: int | None = None) -> Capture:
    """Capture in-memory ``data`` exactly as :func:`read_capture` captures a file."""
    _check_output_chars(max_output_chars)
    keep = data if max_bytes is None else data[: max(max_bytes, 0)]
    blocks = (keep[i : i + READ_CHUNK_BYTES] for i in range(0, len(keep), READ_CHUNK_BYTES))
    return _capture(blocks, len(data), max_output_chars)


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


def _read_only_copy(stack: contextlib.ExitStack, handle: IO[bytes], data: bytes) -> int:
    """Write ``data`` to ``handle``; return a read-only descriptor of it, closed by ``stack``."""
    handle.write(data)
    handle.flush()
    fd = os.open(f"/proc/self/fd/{handle.fileno()}", os.O_RDONLY | os.O_CLOEXEC)
    stack.callback(os.close, fd)
    return fd


def run_launch(
    launch: Launch,
    *,
    timeout_s: float,
    stdin: str | None = None,
    max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> RawResult:
    """Run ``launch`` to completion, or stop it, and return what it did.

    Args:
        launch: The host command line and its environment.
        timeout_s: Wall-clock limit in seconds.
        stdin: Text for the process's standard input (UTF-8, through a read-only
            descriptor); None gives it ``/dev/null``.
        max_capture_bytes: Ceiling on each captured stream: the process is stopped
            when a stream passes it, and only this many bytes of each are kept.
        max_output_chars: Cap on each stream's text (head and tail kept).

    Raises:
        ValueError: ``timeout_s`` or ``max_capture_bytes`` is not positive, or
            ``max_output_chars`` is below :data:`MIN_OUTPUT_CHARS`.
        OSError: The host process could not be started.
    """
    if not timeout_s > 0:
        raise ValueError(f"timeout_s must be positive, got {timeout_s!r}")
    if max_capture_bytes <= 0:
        raise ValueError(f"max_capture_bytes must be positive, got {max_capture_bytes!r}")
    _check_output_chars(max_output_chars)
    with contextlib.ExitStack() as stack:
        out = stack.enter_context(tempfile.TemporaryFile(prefix="receipts-stdout-"))
        err = stack.enter_context(tempfile.TemporaryFile(prefix="receipts-stderr-"))
        source = subprocess.DEVNULL
        if stdin is not None:
            data = stack.enter_context(tempfile.TemporaryFile(prefix="receipts-stdin-"))
            source = _read_only_copy(stack, data, stdin.encode("utf-8"))
        start = time.monotonic()
        proc = subprocess.Popen(
            list(launch.argv),
            stdin=source,
            stdout=out,
            stderr=err,
            cwd=launch.cwd,
            env=dict(launch.env),
            start_new_session=True,
            pass_fds=launch.pass_fds,
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
        marker = launch.stdout_marker
        seen = bool(marker) and os.pread(out.fileno(), len(marker), 0) == marker
        return RawResult(
            exit_code=exit_status(returncode, timed_out),
            stdout=read_capture(
                out.fileno(),
                max_bytes=max_capture_bytes,
                max_output_chars=max_output_chars,
                start=len(marker) if seen else 0,
            ),
            stderr=read_capture(
                err.fileno(), max_bytes=max_capture_bytes, max_output_chars=max_output_chars
            ),
            duration_s=duration,
            timed_out=timed_out,
            overflow=overflow,
            marker_seen=seen,
        )


def not_run(reason: str, *, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> RawResult:
    """The result for a command that was never started, with ``reason`` on stderr.

    The exit code is :data:`CANNOT_RUN_EXIT_CODE`, stdout is empty, and stderr is one
    line starting ``receipts: the command was not run:`` (so it cannot be mistaken
    for output of the command), capped at ``max_output_chars``.
    """
    message = f"receipts: the command was not run: {reason}\n"
    return RawResult(
        exit_code=CANNOT_RUN_EXIT_CODE,
        stdout=capture_bytes(b"", max_output_chars=max_output_chars),
        stderr=capture_bytes(message.encode("utf-8"), max_output_chars=max_output_chars),
        duration_s=0.0,
        timed_out=False,
        overflow=None,
    )


def capture_note(stream: str, capture: Capture, max_capture_bytes: int, *, stopped: bool) -> str:
    """The line appended to stderr for a stream that passed the capture ceiling.

    ``stopped`` says whether the command was stopped for it while it ran; otherwise
    the stream was found over the ceiling after the command ended by itself.
    """
    kept = f"only its first {capture.kept} bytes were kept"
    if stopped:
        return (
            f"\n[receipts: the command was stopped because its {stream} passed "
            f"{max_capture_bytes} bytes; {kept}]\n"
        )
    return (
        f"\n[receipts: its {stream} held {capture.size} bytes, over the capture ceiling "
        f"of {max_capture_bytes} bytes; {kept}]\n"
    )


def to_outcome(
    raw: RawResult,
    *,
    cmd: str,
    cwd: str,
    backend: str,
    max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
) -> CommandOutcome:
    """Build the :class:`CommandOutcome` for ``raw``.

    For each stream that passed the capture ceiling, :func:`capture_note` is appended
    to the capped stderr (the hashes still cover only what the command wrote, up to
    the ceiling).
    """
    notes = [
        capture_note(label, capture, max_capture_bytes, stopped=raw.overflow == label)
        for label, capture in (("stdout", raw.stdout), ("stderr", raw.stderr))
        if raw.overflow == label or capture.size > capture.kept
    ]
    return CommandOutcome(
        cmd=cmd,
        cwd=cwd,
        exit_code=raw.exit_code,
        stdout=raw.stdout.text,
        stderr=raw.stderr.text + "".join(notes),
        duration_s=raw.duration_s,
        timed_out=raw.timed_out,
        stdout_truncated=raw.stdout.truncated,
        stderr_truncated=raw.stderr.truncated,
        stdout_sha256=raw.stdout.sha256,
        stderr_sha256=raw.stderr.sha256,
        backend=backend,
    )
