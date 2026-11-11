"""Tests for the recorder and Stop hook handlers and the hook CLI.

Hook payloads are hand-written to the documented shapes (docs/notes/claude_code_docs.md).
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any

from receipts.hook import __main__ as cli
from receipts.hook import record, stop
from receipts.hook.inputs import HookInput
from receipts.hook.state import HookState
from receipts.ledger.events import Ledger, read_ledger, verify_chain


def hook(event: str, cwd: Path, **fields: Any) -> HookInput:
    return HookInput.parse(
        json.dumps({"hook_event_name": event, "session_id": "s", "cwd": str(cwd), **fields})
    )


def test_bash_pre_post_records_call_result_and_command(tmp_path: Path) -> None:
    ledger, st = tmp_path / "ledger.jsonl", HookState(tmp_path / "state")
    work = tmp_path / "w"
    work.mkdir()
    pre = hook(
        "PreToolUse", work, tool_name="Bash", tool_input={"command": "pytest -q"}, tool_use_id="t1"
    )
    seq = record.handle_pre(pre, ledger, st)
    post = hook(
        "PostToolUseFailure",
        work,
        tool_name="Bash",
        tool_input={"command": "pytest -q"},
        tool_use_id="t1",
        error="Exit code 1\n=== 1 failed, 2 passed in 0.1s ===",
    )
    record.handle_post(post, ledger, st)
    events = read_ledger(ledger)
    assert verify_chain(events) == []
    kinds = [e.kind for e in events]
    assert kinds[:3] == ["tool_call", "tool_result", "command"] and seq == 0
    command = events[2].data
    assert command["exit_code"] == 1 and command["call_seq"] == 0
    assert events[1].data["is_error"] is True


def test_file_edit_records_before_and_after(tmp_path: Path) -> None:
    ledger, st = tmp_path / "ledger.jsonl", HookState(tmp_path / "state")
    work = tmp_path / "w"
    work.mkdir()
    (work / "a.py").write_text("x = 1\n")
    tool_input = {"file_path": str(work / "a.py"), "old_string": "1", "new_string": "2"}
    record.handle_pre(
        hook("PreToolUse", work, tool_name="Edit", tool_input=tool_input, tool_use_id="e1"),
        ledger,
        st,
    )
    (work / "a.py").write_text("x = 2\n")
    record.handle_post(
        hook(
            "PostToolUse",
            work,
            tool_name="Edit",
            tool_input=tool_input,
            tool_use_id="e1",
            tool_response={"filePath": "a.py"},
        ),
        ledger,
        st,
    )
    write = next(e for e in read_ledger(ledger) if e.kind == "file_write").data
    assert write["path"] == "a.py" and write["op"] == "modify"
    assert write["sha256_before"] != write["sha256_after"]
    # A post without a pre (hook started mid-session) still records the call.
    new = {"file_path": "b.py", "content": "y"}
    (work / "b.py").write_text("y")
    record.handle_post(
        hook(
            "PostToolUse",
            work,
            tool_name="Write",
            tool_input=new,
            tool_use_id="w9",
            tool_response={"type": "create"},
        ),
        ledger,
        st,
    )
    events = read_ledger(ledger)
    assert events[-1].kind == "file_write" and events[-1].data["op"] == "create"
    assert verify_chain(events) == []


def test_concurrent_hooks_keep_the_chain_intact(tmp_path: Path) -> None:
    ledger, st = tmp_path / "ledger.jsonl", HookState(tmp_path / "state")
    work = tmp_path / "w"
    work.mkdir()

    def fire(i: int) -> None:
        record.handle_pre(
            hook(
                "PreToolUse",
                work,
                tool_name="Read",
                tool_input={"file_path": "x"},
                tool_use_id=f"r{i}",
            ),
            ledger,
            st,
        )

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = read_ledger(ledger)
    assert len(events) == 12 and verify_chain(events) == []


def seed_failing_ledger(tmp_path: Path) -> Path:
    ledger, st = tmp_path / "ledger.jsonl", HookState(tmp_path / "state")
    work = tmp_path / "w"
    work.mkdir(parents=True, exist_ok=True)
    record.handle_pre(
        hook(
            "PreToolUse",
            work,
            tool_name="Bash",
            tool_input={"command": "pytest -q"},
            tool_use_id="t1",
        ),
        ledger,
        st,
    )
    record.handle_post(
        hook(
            "PostToolUseFailure",
            work,
            tool_name="Bash",
            tool_input={"command": "pytest -q"},
            tool_use_id="t1",
            error="Exit code 1\n=== 1 failed, 2 passed in 0.1s ===",
        ),
        ledger,
        st,
    )
    return ledger


def test_stop_blocks_on_contradicted_claims(tmp_path: Path) -> None:
    ledger = seed_failing_ledger(tmp_path)
    decision = stop.stop_decision(
        hook("Stop", tmp_path, last_assistant_message="Done. All tests pass."), ledger
    )
    assert decision is not None and decision["decision"] == "block"
    assert "All tests pass" in decision["reason"] and "corrected final report" in decision["reason"]
    assert (
        stop.stop_decision(
            hook("Stop", tmp_path, stop_hook_active=True, last_assistant_message="All tests pass."),
            ledger,
        )
        is None
    )
    assert stop.stop_decision(hook("Stop", tmp_path, last_assistant_message="  "), ledger) is None
    assert (
        stop.stop_decision(
            hook("Stop", tmp_path, last_assistant_message="All tests pass."),
            tmp_path / "missing.jsonl",
        )
        is None
    )
    honest = stop.stop_decision(
        hook("Stop", tmp_path, last_assistant_message="One test still fails."), ledger
    )
    assert honest is None
    assert (
        stop.stop_decision(hook("Stop", tmp_path, last_assistant_message="Hello there."), ledger)
        is None
    )


def test_format_reason_caps_the_list() -> None:
    from receipts.claims.types import Claim, ClaimType
    from receipts.verify import Label, Verdict

    pairs = [
        (
            Claim(f"c{i}", ClaimType.TESTS_PASS, f"claim {i}", (0, 1)),
            Verdict(f"c{i}", Label.CONTRADICTED, (1,), "evidence", "x"),
        )
        for i in range(7)
    ]
    reason = stop.format_reason(pairs)
    assert "and 2 more" in reason and reason.count('"claim') == stop.MAX_LISTED
    assert stop.contradicted([p[0] for p in pairs[:2]], [pairs[0][1]]) == [pairs[0]]


def test_cli_never_fails(tmp_path: Path) -> None:
    out = io.StringIO()
    args = ["record", "--ledger", str(tmp_path / "l.jsonl"), "--state", str(tmp_path / "s")]
    assert cli.run(args, io.StringIO("not json"), out) == 0
    assert "HookInputError" in (tmp_path / "s" / "errors.log").read_text()
    assert out.getvalue() == ""
    ledger = seed_failing_ledger(tmp_path / "x")
    stop_args = ["stop", "--ledger", str(ledger), "--state", str(tmp_path / "s")]
    payload = json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": "s",
            "cwd": str(tmp_path),
            "last_assistant_message": "All tests pass.",
        }
    )
    assert cli.run(stop_args, io.StringIO(payload), out) == 0
    assert json.loads(out.getvalue())["decision"] == "block"
    timings = (tmp_path / "s" / "timings.log").read_text().splitlines()
    assert [t.split()[0] for t in timings] == ["record", "stop"]
    other = json.dumps({"hook_event_name": "Notification", "session_id": "s", "cwd": "."})
    assert cli.run(args, io.StringIO(other), io.StringIO()) == 0
    assert Ledger.load(ledger)


def test_cli_ledger_dir_per_session(tmp_path: Path) -> None:
    base = tmp_path / "sessions"
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "abc/../1",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "t1",
        }
    )
    assert cli.run(["record", "--ledger-dir", str(base)], io.StringIO(payload), io.StringIO()) == 0
    ledger = base / "abc_.._1.jsonl"
    assert ledger.is_file() and read_ledger(ledger)[0].kind == "tool_call"
    assert (base / "abc_.._1.state" / "timings.log").is_file()
    assert cli.session_paths(base, "")[0].name == "unknown-session.jsonl"
    cli.run(["record", "--ledger-dir", str(base)], io.StringIO("junk"), io.StringIO())
    assert "HookInputError" in (base / "_errors" / "errors.log").read_text()


def test_cli_requires_paths(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit):
        cli.run(["record", "--ledger", str(tmp_path / "l")], io.StringIO(""), io.StringIO())
