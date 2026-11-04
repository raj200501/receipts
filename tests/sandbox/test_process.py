"""Tests for starting, capturing, capping, and stopping one host process.

These run plain local processes (``bash -c``) with no sandbox: the commands are
this test file's own fixtures.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from receipts.sandbox import process as process_module
from receipts.sandbox.process import (
    TIMEOUT_EXIT_CODE,
    Launch,
    RawResult,
    exit_status,
    overflow_note,
    run_launch,
    to_outcome,
)

from .helpers import background_sleeper, processes_with, unique_marker, wait_until_gone

BASH = shutil.which("bash") or "/bin/bash"
ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


def launch(script: str, cwd: Path, stop: Callable[[], None] | None = None) -> Launch:
    return Launch(argv=(BASH, "-c", "--", script), env=ENV, cwd=cwd, stop=stop)


def raw(stdout: bytes = b"", stderr: bytes = b"", overflow: str | None = None) -> RawResult:
    return RawResult(0, stdout, stderr, 0.5, False, overflow)


def test_exit_status_maps_signals_and_timeouts() -> None:
    assert exit_status(0, False) == 0
    assert exit_status(3, False) == 3
    assert exit_status(-9, False) == 137
    assert exit_status(-15, False) == 143
    assert exit_status(0, True) == TIMEOUT_EXIT_CODE


def test_streams_and_exit_code_are_captured(tmp_path: Path) -> None:
    result = run_launch(launch("echo out; echo err >&2; exit 4", tmp_path), timeout_s=10)
    assert (result.exit_code, result.stdout, result.stderr) == (4, b"out\n", b"err\n")
    assert not result.timed_out and result.overflow is None
    assert 0 <= result.duration_s < 10


def test_stdin_is_passed_and_defaults_to_dev_null(tmp_path: Path) -> None:
    assert run_launch(launch("cat", tmp_path), timeout_s=10, stdin="hello\n").stdout == b"hello\n"
    assert run_launch(launch("cat", tmp_path), timeout_s=10).stdout == b""


def test_environment_and_cwd_are_exactly_the_launch_values(tmp_path: Path) -> None:
    result = run_launch(launch("pwd; env", tmp_path), timeout_s=10)
    lines = result.stdout.decode().splitlines()
    assert lines[0] == str(tmp_path)
    names = {line.split("=", 1)[0] for line in lines[1:]}
    assert names - {"PWD", "SHLVL", "_"} == set(ENV)


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
    assert len(result.stdout) > 50_000
    assert calls == ["stop", "stop"]


def test_flooding_stderr_is_named(tmp_path: Path) -> None:
    result = run_launch(launch("yes >&2", tmp_path), timeout_s=30, max_capture_bytes=50_000)
    assert result.overflow == "stderr"


@pytest.mark.parametrize(("timeout_s", "cap"), [(0, 10), (-1, 10), (1, 0)])
def test_invalid_limits_are_refused(tmp_path: Path, timeout_s: float, cap: int) -> None:
    with pytest.raises(ValueError):
        run_launch(launch("true", tmp_path), timeout_s=timeout_s, max_capture_bytes=cap)


def test_to_outcome_caps_head_and_tail_and_hashes_the_full_stream() -> None:
    text = "H" * 600 + "x" * 5000 + "T" * 600
    outcome = to_outcome(
        raw(stdout=text.encode()), cmd="c", cwd="sub", backend="bwrap", max_output_chars=1000
    )
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
    outcome = to_outcome(
        raw(stdout=b"ok \xff\xfe end"), cmd="c", cwd=".", backend="fake", max_output_chars=100
    )
    assert outcome.stdout == "ok \ufffd\ufffd end"


def test_to_outcome_notes_an_overflow_after_hashing() -> None:
    outcome = to_outcome(
        raw(stdout=b"y\n" * 10, stderr=b"e", overflow="stdout"),
        cmd="yes",
        cwd=".",
        backend="fake",
        max_output_chars=100,
        max_capture_bytes=20,
    )
    assert outcome.stderr == "e" + overflow_note("stdout", 20)
    assert "stdout passed 20 bytes" in outcome.stderr
    assert outcome.stderr_sha256 == hashlib.sha256(b"e").hexdigest()


def test_a_pid_that_is_not_our_child_counts_as_exited() -> None:
    from receipts.sandbox.process import _has_exited

    assert _has_exited(1)
