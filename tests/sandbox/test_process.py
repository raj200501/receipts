"""Tests for starting, capturing, capping, and stopping one host process.

These run plain local processes (``bash -c``) with no sandbox: the commands are
this test file's own fixtures.
"""

from __future__ import annotations

import errno
import hashlib
import os
import random
import shutil
import tempfile
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pytest

from receipts.ledger.events import cap_stream
from receipts.sandbox import process as process_module
from receipts.sandbox.process import (
    CANNOT_RUN_EXIT_CODE,
    MIN_OUTPUT_CHARS,
    TIMEOUT_EXIT_CODE,
    Capture,
    Launch,
    RawResult,
    capture_bytes,
    capture_note,
    exit_status,
    not_run,
    read_capture,
    run_launch,
    to_outcome,
)

from .helpers import background_sleeper, processes_with, unique_marker, wait_until_gone

BASH = shutil.which("bash") or "/bin/bash"
ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


def launch(
    script: str,
    cwd: Path,
    stop: Callable[[], None] | None = None,
    *,
    pass_fds: tuple[int, ...] = (),
    marker: bytes = b"",
) -> Launch:
    """A launch that runs ``script`` with plain ``bash -c`` (no sandbox)."""
    return Launch(
        argv=(BASH, "-c", "--", script),
        env=ENV,
        cwd=cwd,
        stop=stop,
        pass_fds=pass_fds,
        stdout_marker=marker,
    )


def raw(stdout: bytes = b"", stderr: bytes = b"", overflow: str | None = None) -> RawResult:
    """A synthetic result whose streams are captured from ``stdout`` and ``stderr``."""
    return RawResult(
        exit_code=0,
        stdout=capture_bytes(stdout, max_output_chars=1000),
        stderr=capture_bytes(stderr, max_output_chars=1000),
        duration_s=0.5,
        timed_out=False,
        overflow=overflow,
    )


def test_exit_status_maps_signals_and_timeouts() -> None:
    assert exit_status(0, False) == 0
    assert exit_status(3, False) == 3
    assert exit_status(-9, False) == 137
    assert exit_status(-15, False) == 143
    assert exit_status(0, True) == TIMEOUT_EXIT_CODE


def test_streams_and_exit_code_are_captured(tmp_path: Path) -> None:
    result = run_launch(launch("echo out; echo err >&2; exit 4", tmp_path), timeout_s=10)
    assert (result.exit_code, result.stdout.text, result.stderr.text) == (4, "out\n", "err\n")
    assert (result.stdout.size, result.stdout.kept) == (4, 4)
    assert not result.timed_out and result.overflow is None and not result.marker_seen
    assert 0 <= result.duration_s < 10


def test_stdin_is_passed_and_defaults_to_dev_null(tmp_path: Path) -> None:
    piped = run_launch(launch("cat", tmp_path), timeout_s=10, stdin="hello\n")
    assert piped.stdout.text == "hello\n"
    assert run_launch(launch("cat", tmp_path), timeout_s=10).stdout.text == ""


def test_stdin_is_read_only(tmp_path: Path) -> None:
    script = (
        'python3 -c "import os\n'
        "try:\n    os.write(0, b'x')\nexcept OSError as e:\n    print('write', e.errno)\n"
        "try:\n    os.ftruncate(0, 1 << 30)\nexcept OSError as e:\n    print('truncate', e.errno)\n"
        'print(os.read(0, 100).decode())"'
    )
    result = run_launch(launch(script, tmp_path), timeout_s=30, stdin="given input")
    lines = result.stdout.text.splitlines()
    assert lines[0] == f"write {errno.EBADF}"
    assert lines[1] in (f"truncate {errno.EBADF}", f"truncate {errno.EINVAL}")
    assert lines[2] == "given input"


def test_environment_and_cwd_are_exactly_the_launch_values(tmp_path: Path) -> None:
    result = run_launch(launch("pwd; env", tmp_path), timeout_s=10)
    lines = result.stdout.text.splitlines()
    assert lines[0] == str(tmp_path)
    names = {line.split("=", 1)[0] for line in lines[1:]}
    assert names - {"PWD", "SHLVL", "_"} == set(ENV)


def test_pass_fds_reach_the_process(tmp_path: Path) -> None:
    read_fd, write_fd = os.pipe()
    try:
        result = run_launch(
            launch(f"echo via-fd >&{write_fd}", tmp_path, pass_fds=(write_fd,)), timeout_s=10
        )
        os.close(write_fd)
        write_fd = -1
        assert result.exit_code == 0
        assert os.read(read_fd, 100) == b"via-fd\n"
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def test_a_stdout_marker_is_removed_and_reported(tmp_path: Path) -> None:
    marker = b"synthetic-start-marker\n"
    seen = run_launch(
        launch("printf 'synthetic-start-marker\\nrest'", tmp_path, marker=marker), timeout_s=10
    )
    assert seen.marker_seen and seen.stdout.text == "rest"
    assert seen.stdout.sha256 == hashlib.sha256(b"rest").hexdigest()
    absent = run_launch(launch("printf 'other output'", tmp_path, marker=marker), timeout_s=10)
    assert not absent.marker_seen and absent.stdout.text == "other output"


def test_signal_death_reports_128_plus_signal(tmp_path: Path) -> None:
    assert run_launch(launch("kill -TERM $$", tmp_path), timeout_s=10).exit_code == 143


def test_timeout_kills_the_process_group(tmp_path: Path) -> None:
    marker = unique_marker()
    result = run_launch(launch(f"{background_sleeper(marker)} sleep 60", tmp_path), timeout_s=0.5)
    assert result.timed_out and result.exit_code == TIMEOUT_EXIT_CODE
    assert 0.4 < result.duration_s < 5
    assert wait_until_gone(marker)


def test_background_processes_do_not_outlive_the_command(tmp_path: Path) -> None:
    marker = unique_marker()
    result = run_launch(launch(f"{background_sleeper(marker)} exit 0", tmp_path), timeout_s=10)
    assert result.exit_code == 0 and not result.timed_out
    assert wait_until_gone(marker)
    assert processes_with(marker) == []


def test_stop_step_runs_on_timeout_only(tmp_path: Path) -> None:
    calls: list[str] = []
    quick = launch("true", tmp_path, stop=lambda: calls.append("stop"))
    run_launch(quick, timeout_s=10)
    assert calls == []
    slow = launch("sleep 30", tmp_path, stop=lambda: calls.append("stop"))
    assert run_launch(slow, timeout_s=0.3).timed_out
    assert calls == ["stop", "stop"]


def test_stop_step_runs_before_the_kill_and_again_after_the_process_is_gone(
    tmp_path: Path,
) -> None:
    marker = unique_marker()
    seen: list[bool] = []

    def stop() -> None:
        seen.append(bool(processes_with(marker)))

    cmd = f"exec -a {marker} sleep 30"
    assert run_launch(launch(cmd, tmp_path, stop=stop), timeout_s=0.5).timed_out
    assert seen == [True, False]


def test_an_interrupted_wait_still_stops_and_kills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = unique_marker()
    calls: list[str] = []

    def interrupted(*args: object) -> tuple[bool, str | None]:
        raise KeyboardInterrupt

    monkeypatch.setattr(process_module, "_wait", interrupted)
    cmd = f"exec -a {marker} sleep 30"
    with pytest.raises(KeyboardInterrupt):
        run_launch(launch(cmd, tmp_path, stop=lambda: calls.append("stop")), timeout_s=10)
    assert calls == ["stop", "stop"]
    assert wait_until_gone(marker)


def test_flooding_output_stops_the_command(tmp_path: Path) -> None:
    calls: list[str] = []
    result = run_launch(
        launch("yes", tmp_path, stop=lambda: calls.append("stop")),
        timeout_s=30,
        max_capture_bytes=50_000,
    )
    assert result.overflow == "stdout" and not result.timed_out
    assert result.exit_code == 137
    assert result.stdout.size > 50_000 and result.stdout.kept == 50_000
    assert result.stdout.truncated
    assert result.stdout.sha256 == hashlib.sha256(b"y\n" * 25_000).hexdigest()
    assert calls == ["stop", "stop"]


def test_flooding_stderr_is_named(tmp_path: Path) -> None:
    result = run_launch(launch("yes >&2", tmp_path), timeout_s=30, max_capture_bytes=50_000)
    assert result.overflow == "stderr"


def test_a_sparse_stream_is_read_in_bounded_memory(tmp_path: Path) -> None:
    # The command grows its stdout file to 1 TiB at no cost (a sparse file) and exits
    # before any poll sees it: only the first max_capture_bytes are read, in chunks.
    script = "python3 -c 'import os; os.ftruncate(1, 1 << 40)'"
    tracemalloc.start()
    try:
        result = run_launch(
            launch(script, tmp_path), timeout_s=30, max_capture_bytes=4 << 20, max_output_chars=100
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.exit_code == 0 and result.overflow is None
    assert (result.stdout.size, result.stdout.kept) == (1 << 40, 4 << 20)
    assert result.stdout.truncated and len(result.stdout.text) < 200
    assert result.stdout.sha256 == hashlib.sha256(b"\0" * (4 << 20)).hexdigest()
    assert peak < 8 << 20


def test_a_stream_found_over_the_ceiling_after_exit_gets_a_note(tmp_path: Path) -> None:
    script = "python3 -c 'import os; os.ftruncate(1, 1 << 30)'"
    result = run_launch(launch(script, tmp_path), timeout_s=30, max_capture_bytes=1000)
    outcome = to_outcome(result, cmd="c", cwd=".", backend="fake", max_capture_bytes=1000)
    assert outcome.exit_code == 0 and outcome.stdout_truncated
    assert outcome.stderr == capture_note("stdout", result.stdout, 1000, stopped=False)
    assert "held 1073741824 bytes, over the capture ceiling of 1000 bytes" in outcome.stderr


@pytest.mark.parametrize(("timeout_s", "cap", "chars"), [(0, 10, 10), (-1, 10, 10), (1, 0, 10)])
def test_invalid_limits_are_refused(tmp_path: Path, timeout_s: float, cap: int, chars: int) -> None:
    with pytest.raises(ValueError):
        run_launch(
            launch("true", tmp_path),
            timeout_s=timeout_s,
            max_capture_bytes=cap,
            max_output_chars=chars,
        )


def test_max_output_chars_below_two_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 2"):
        run_launch(launch("true", tmp_path), timeout_s=10, max_output_chars=1)
    with pytest.raises(ValueError, match="at least 2"):
        capture_bytes(b"x", max_output_chars=MIN_OUTPUT_CHARS - 1)


#: Synthetic stream contents: ASCII, multibyte text, and bytes that are not UTF-8.
SAMPLES: tuple[bytes, ...] = (
    b"",
    b"short",
    b"H" * 600 + b"x" * 5000 + b"T" * 600,
    ("\u00e9t\u00e9 \u2603 \U0001f600 " * 300).encode(),
    b"ok \xff\xfe end \xe2\x82 cut \xf0\x9f\x98" * 200,
    bytes(random.Random(7).randrange(256) for _ in range(5000)),
)


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 4096])
@pytest.mark.parametrize("max_chars", [2, 3, 10, 999, 1000, 100_000])
def test_capture_matches_cap_stream_however_the_stream_is_chunked(
    monkeypatch: pytest.MonkeyPatch, chunk: int, max_chars: int
) -> None:
    monkeypatch.setattr(process_module, "READ_CHUNK_BYTES", chunk)
    for data in SAMPLES:
        text, cut, digest = cap_stream(data.decode("utf-8", errors="replace"), max_chars)
        captured = capture_bytes(data, max_output_chars=max_chars)
        assert (captured.text, captured.truncated, captured.sha256) == (text, cut, digest)
        assert (captured.size, captured.kept) == (len(data), len(data))


def test_read_capture_reads_a_file_from_an_offset(tmp_path: Path) -> None:
    data = b"PREFIX" + "\u00e9".encode() * 3000
    with tempfile.TemporaryFile(dir=tmp_path) as handle:
        handle.write(data)
        handle.flush()
        captured = read_capture(handle.fileno(), max_bytes=10_000, max_output_chars=50, start=6)
        assert captured == capture_bytes(data[6:], max_output_chars=50)
        limited = read_capture(handle.fileno(), max_bytes=10, max_output_chars=50)
        assert (limited.text, limited.size, limited.kept) == ("PREFIX\u00e9\u00e9", len(data), 10)
        assert limited.truncated
        with pytest.raises(ValueError, match="negative"):
            read_capture(handle.fileno(), max_bytes=-1, max_output_chars=50)


def test_read_capture_survives_a_file_that_shrinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with tempfile.TemporaryFile(dir=tmp_path) as handle:
        handle.write(b"abcdef" * 1000)
        handle.flush()
        monkeypatch.setattr(process_module, "READ_CHUNK_BYTES", 100)
        real = os.pread
        calls = []

        def shrinking(fd: int, size: int, offset: int) -> bytes:
            calls.append(offset)
            return real(fd, size, offset) if len(calls) == 1 else b""

        monkeypatch.setattr(os, "pread", shrinking)
        captured = read_capture(handle.fileno(), max_bytes=6000, max_output_chars=1000)
    assert (captured.size, captured.kept) == (6000, 100)
    assert captured.truncated and captured.text == "abcdef" * 16 + "abcd"


def test_capture_bytes_honours_max_bytes() -> None:
    captured = capture_bytes(b"0123456789", max_output_chars=100, max_bytes=4)
    assert (captured.text, captured.size, captured.kept, captured.truncated) == (
        "0123",
        10,
        4,
        True,
    )


def test_not_run_reports_the_reason_capped() -> None:
    result = not_run("synthetic reason")
    assert result.exit_code == CANNOT_RUN_EXIT_CODE and result.stdout.text == ""
    assert result.stderr.text == "receipts: the command was not run: synthetic reason\n"
    short = not_run("synthetic reason " * 20, max_output_chars=10)
    assert short.stderr.truncated and short.stderr.text.startswith("recei")


def test_to_outcome_caps_head_and_tail_and_hashes_the_full_stream() -> None:
    text = "H" * 600 + "x" * 5000 + "T" * 600
    outcome = to_outcome(raw(stdout=text.encode()), cmd="c", cwd="sub", backend="bwrap")
    assert outcome.stdout_truncated and not outcome.stderr_truncated
    assert outcome.stdout.startswith("H" * 500) and outcome.stdout.endswith("T" * 500)
    assert "elided by receipts" in outcome.stdout
    assert outcome.stdout_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert (outcome.cmd, outcome.cwd, outcome.backend, outcome.exit_code) == (
        "c",
        "sub",
        "bwrap",
        0,
    )


def test_to_outcome_replaces_invalid_utf8() -> None:
    outcome = to_outcome(raw(stdout=b"ok \xff\xfe end"), cmd="c", cwd=".", backend="fake")
    assert outcome.stdout == "ok \ufffd\ufffd end"


def test_to_outcome_notes_a_stop_for_output_after_hashing() -> None:
    stdout = Capture(text="y\n" * 10, truncated=True, sha256="0" * 64, size=30, kept=20)
    stderr = capture_bytes(b"e", max_output_chars=100)
    result = RawResult(0, stdout, stderr, 0.5, False, "stdout")
    outcome = to_outcome(result, cmd="yes", cwd=".", backend="fake", max_capture_bytes=20)
    assert outcome.stderr == "e" + capture_note("stdout", stdout, 20, stopped=True)
    assert "stopped because its stdout passed 20 bytes; only its first 20 bytes" in outcome.stderr
    assert outcome.stderr_sha256 == hashlib.sha256(b"e").hexdigest()
    assert outcome.stdout_truncated


def test_a_pid_that_is_not_our_child_counts_as_exited() -> None:
    from receipts.sandbox.process import _has_exited

    assert _has_exited(1)
