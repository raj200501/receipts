"""Tests for the Recorder: typed payloads, derived runs, validation, and chain integrity."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from receipts.ledger.events import MAX_STREAM_CHARS, Ledger, LedgerWriter, sha256_text, verify_chain
from receipts.ledger.recorder import Recorder, sha256_bytes

from .helpers import assert_payload_shape, fixture, outcome


@pytest.fixture
def recorder(tmp_path: Path) -> Recorder:
    return Recorder(LedgerWriter(tmp_path / "ledger.jsonl"), workspace=Path("/work/calc"))


def _start(recorder: Recorder) -> int:
    return recorder.record_run_start(
        run_id="run-1",
        task_id="calc-001",
        agent="minimal-agent",
        model="example-model@rev0",
        config_id="cfg-a",
        workspace="/work/calc",
        base_commit="abc123",
        conditions={"M2": "truncated"},
    )


def test_full_run_writes_well_formed_events(recorder: Recorder, tmp_path: Path) -> None:
    """A synthetic run (test data, not a real agent run) touching every event kind."""
    assert _start(recorder) == 0
    call = recorder.record_tool_call("bash", {"cmd": "uv run pytest -q"})
    cmd_seq = recorder.record_command(
        outcome("uv run pytest -q", fixture("pytest/quiet_fail.txt"), exit_code=1), call, "agent"
    )
    recorder.record_tool_result(call, "1 failed, 5 passed", full_chars=900)
    edit = recorder.record_tool_call("write", {"path": "src/io.py"})
    recorder.record_file_write("/work/calc/src/io.py", b"old", b"new", call_seq=edit)
    recorder.record_diff(
        "abc123",
        [{"path": "src/io.py", "status": "M", "added": 1, "removed": 1}],
        [
            {
                "manifest": "requirements.txt",
                "name": "rich",
                "change": "added",
                "old": None,
                "new": ">=13",
            }
        ],
    )
    recorder.record_hidden_checks([{"name": "roundtrip", "passed": True, "requirement": "R1"}])
    recorder.record_run_end(
        "Fixed the roundtrip bug; all tests pass.", turns=4, stop_reason="finished"
    )

    ledger = Ledger.load(tmp_path / "ledger.jsonl")
    assert [e.kind for e in ledger] == [
        "run_start",
        "tool_call",
        "command",
        "test_run",
        "tool_result",
        "tool_call",
        "file_write",
        "diff",
        "hidden_check",
        "run_end",
    ]
    for event in ledger:
        assert_payload_shape(event.kind, event.data)
    assert verify_chain(ledger.events) == []
    test_run = ledger.get(3)
    assert test_run.data["command_seq"] == cmd_seq
    assert test_run.data["source"] == "agent"
    assert test_run.data["failing"] == ["tests/test_io.py::test_roundtrip"]
    assert ledger.get(0).data["conditions"] == {"M2": "truncated"}
    assert ledger.get(0).source == "harness"
    hidden = ledger.get(8).data
    assert (hidden["passed"], hidden["failed"], hidden["total"]) == (1, 0, 1)


def test_run_start_must_be_first_and_conditions_are_optional(recorder: Recorder) -> None:
    recorder.record_tool_call("bash", {"cmd": "ls"})
    with pytest.raises(ValueError, match="first event"):
        _start(recorder)
    other = Recorder(LedgerWriter(recorder.writer.path.with_name("other.jsonl")))
    other.record_run_start(
        run_id="r",
        task_id="t",
        agent="a",
        model="m",
        config_id="c",
        workspace="/w",
        base_commit="b",
    )
    assert "conditions" not in other.writer.events[0].data


def test_nothing_may_follow_run_end(recorder: Recorder) -> None:
    recorder.record_run_end("done", turns=1, stop_reason="finished")
    with pytest.raises(ValueError, match="run_end"):
        recorder.record_tool_call("bash", {})
    with pytest.raises(ValueError, match="run_end"):
        recorder.record_run_end("again", turns=1, stop_reason="finished")


def test_invalid_source_is_rejected(recorder: Recorder) -> None:
    with pytest.raises(ValueError, match="source must be one of"):
        recorder.record_tool_call("bash", {}, source="transcript")  # type: ignore[arg-type]  # deliberate bad value
    assert recorder.writer.events == ()


def test_tool_result_truncation_info(recorder: Recorder) -> None:
    call = recorder.record_tool_call("Bash", {"command": "pytest"})
    full = recorder.record_tool_result(call, "all output")
    cut = recorder.record_tool_result(call, "head", full_chars=5000, is_error=True)
    noted = recorder.record_tool_result(
        call, "x" * 20 + "\n[output truncated]", full_chars=25, truncated=True, tool="Bash2"
    )
    events = recorder.writer.events
    assert events[full].data == {
        "tool": "Bash",
        "call_seq": call,
        "shown": "all output",
        "shown_chars": 10,
        "full_chars": 10,
        "truncated": False,
        "is_error": False,
        "source": "agent",
    }
    assert (events[cut].data["truncated"], events[cut].data["is_error"]) == (True, True)
    assert events[cut].data["full_chars"] == 5000
    assert (events[noted].data["truncated"], events[noted].data["tool"]) == (True, "Bash2")


def test_tool_result_and_command_need_a_real_tool_call(recorder: Recorder) -> None:
    _start(recorder)
    with pytest.raises(ValueError, match="call_seq 0 is not a tool_call"):
        recorder.record_tool_result(0, "x")
    with pytest.raises(ValueError, match="call_seq 9"):
        recorder.record_command(outcome("ls"), 9, "agent")
    with pytest.raises(ValueError, match="call_seq -1"):
        recorder.record_file_write("a.py", None, b"x", call_seq=-1)


def test_command_payload_and_derived_lint_and_typecheck(recorder: Recorder) -> None:
    out = outcome("make ci", fixture("mixed/make_ci.txt"), "warning: x\n", exit_code=0)
    seq = recorder.record_command(out, None, "harness")
    events = recorder.writer.events
    command = events[seq].data
    assert command == {
        "cmd": "make ci",
        "cwd": ".",
        "exit_code": 0,
        "duration_s": 0.01,
        "stdout": out.stdout,
        "stderr": "warning: x\n",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_sha256": sha256_text(out.stdout),
        "stderr_sha256": sha256_text("warning: x\n"),
        "timed_out": False,
        "call_seq": None,
        "source": "harness",
    }
    derived = [(e.kind, e.data.get("framework") or e.data.get("tool")) for e in events[seq + 1 :]]
    assert derived == [
        ("test_run", "pytest"),
        ("lint_run", "ruff"),
        ("lint_run", "ruff-format"),
        ("typecheck_run", "mypy"),
    ]
    for event in events[seq + 1 :]:
        assert event.data["command_seq"] == seq
        assert event.data["source"] == "harness"
        assert_payload_shape(event.kind, event.data)


def test_derive_false_and_viewer_commands_write_only_the_command(recorder: Recorder) -> None:
    text = fixture("pytest/quiet_pass.txt")
    recorder.record_command(
        outcome("uv run python hidden.py", text), None, "snapshot", derive=False
    )
    recorder.record_command(outcome("cat old-run.log", text), None, "agent")
    assert [e.kind for e in recorder.writer.events] == ["command", "command"]


def test_long_streams_are_capped_but_keep_the_full_hash(recorder: Recorder) -> None:
    big = "x" * (MAX_STREAM_CHARS + 100) + "\n3 passed in 0.1s\n"
    raw = outcome("pytest", "")
    seq = recorder.record_command(
        type(raw)(**{**raw.__dict__, "stdout": big, "stdout_sha256": sha256_text(big)}),
        None,
        "agent",
    )
    data = recorder.writer.events[seq].data
    assert data["stdout_truncated"] is True
    assert data["stdout_sha256"] == sha256_text(big)
    assert len(data["stdout"]) < len(big)
    assert data["stdout"].endswith("3 passed in 0.1s\n")
    assert recorder.writer.events[seq + 1].data["passed"] == 3


def test_sandbox_truncation_flag_is_kept(recorder: Recorder) -> None:
    raw = outcome("pytest", "partial")
    flagged = type(raw)(**{**raw.__dict__, "stderr_truncated": True, "timed_out": True})
    seq = recorder.record_command(flagged, None, "agent")
    data = recorder.writer.events[seq].data
    assert (data["stderr_truncated"], data["stdout_truncated"], data["timed_out"]) == (
        True,
        False,
        True,
    )


def test_file_write_ops_and_hashes(recorder: Recorder) -> None:
    created = recorder.record_file_write("src/new.py", None, b"print(1)\n")
    modified = recorder.record_file_write(
        PurePosixPath("./src/new.py"), b"print(1)\n", b"print(2)\n"
    )
    same = recorder.record_file_write("src/new.py", b"a", b"a")
    deleted = recorder.record_file_write(PureWindowsPath("src\\new.py"), b"print(2)\n", None)
    events = recorder.writer.events
    assert events[created].data == {
        "path": "src/new.py",
        "op": "create",
        "sha256_before": None,
        "sha256_after": hashlib.sha256(b"print(1)\n").hexdigest(),
        "call_seq": None,
        "source": "agent",
    }
    assert events[modified].data["op"] == "modify"
    assert events[modified].data["path"] == "src/new.py"
    assert events[same].data["sha256_before"] == events[same].data["sha256_after"]
    assert events[deleted].data["op"] == "delete"
    assert events[deleted].data["path"] == "src/new.py"
    assert events[deleted].data["sha256_after"] is None
    assert sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()


def test_file_write_absolute_paths_and_bad_paths(recorder: Recorder, tmp_path: Path) -> None:
    seq = recorder.record_file_write("/work/calc/src/a.py", b"1", b"2")
    assert recorder.writer.events[seq].data["path"] == "src/a.py"
    with pytest.raises(ValueError, match="outside the workspace"):
        recorder.record_file_write("/etc/passwd", b"1", b"2")
    with pytest.raises(ValueError, match="inside the workspace"):
        recorder.record_file_write("../escape.py", b"1", b"2")
    with pytest.raises(ValueError, match="inside the workspace"):
        recorder.record_file_write(".", b"1", b"2")
    with pytest.raises(ValueError, match="before, after, or both"):
        recorder.record_file_write("a.py", None, None)
    bare = Recorder(LedgerWriter(tmp_path / "bare.jsonl"))
    with pytest.raises(ValueError, match="needs a workspace"):
        bare.record_file_write("/work/calc/a.py", None, b"x")


def test_resumed_recorder_extends_the_same_chain(recorder: Recorder) -> None:
    _start(recorder)
    path = recorder.writer.path
    resumed = Recorder(LedgerWriter(path))
    call = resumed.record_tool_call("bash", {"cmd": "ls"})
    assert call == 1
    assert verify_chain(Ledger.load(path).events) == []
