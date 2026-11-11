"""Tests for hook input parsing, tool mapping, settings generation, and state.

Hook payloads below are hand-written to the documented shapes
(docs/notes/claude_code_docs.md), not recorded from live sessions.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

import pytest

from receipts.hook import inputs, settings, state


def payload(event: str, **fields: Any) -> str:
    return json.dumps({"hook_event_name": event, "session_id": "s1", "cwd": "/w", **fields})


def test_parse_minimal_and_full() -> None:
    hook = inputs.HookInput.parse(
        payload(
            "PreToolUse", tool_name="Bash", tool_input={"command": "pytest -q"}, tool_use_id="t1"
        )
    )
    assert (hook.event, hook.tool_name, hook.tool_use_id) == ("PreToolUse", "Bash", "t1")
    stop = inputs.HookInput.parse(
        payload("Stop", stop_hook_active=True, last_assistant_message="Done.")
    )
    assert stop.stop_hook_active and stop.last_assistant_message == "Done."
    odd = inputs.HookInput.parse(payload("PreToolUse", tool_input="raw"))
    assert odd.tool_input == {"value": "raw"}


@pytest.mark.parametrize("text", ["not json", "[1]", '{"session_id": "x"}'])
def test_parse_rejects(text: str) -> None:
    with pytest.raises(inputs.HookInputError):
        inputs.HookInput.parse(text)


def test_bash_outcome_success_failure_interrupt() -> None:
    ok = inputs.HookInput.parse(
        payload(
            "PostToolUse",
            tool_name="Bash",
            tool_input={"command": "pytest -q"},
            tool_response={
                "stdout": "3 passed",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
            },
        )
    )
    assert inputs.bash_outcome(ok) == inputs.BashOutcome("pytest -q", "3 passed", "", 0, False)
    fail = inputs.HookInput.parse(
        payload(
            "PostToolUseFailure",
            tool_name="Bash",
            tool_input={"command": "pytest"},
            error="Exit code 1\n1 failed, 2 passed",
        )
    )
    out = inputs.bash_outcome(fail)
    assert out.exit_code == 1 and "1 failed" in out.stderr
    nocode = inputs.HookInput.parse(
        payload("PostToolUseFailure", tool_name="Bash", tool_input={"command": "x"}, error="boom")
    )
    assert inputs.bash_outcome(nocode).exit_code == 1
    intr = inputs.HookInput.parse(
        payload(
            "PostToolUse",
            tool_name="Bash",
            tool_input={"command": "sleep 9"},
            tool_response={"interrupted": True},
        )
    )
    assert inputs.bash_outcome(intr).exit_code == 130
    with_out = inputs.HookInput.parse(
        payload(
            "PostToolUseFailure",
            tool_name="Bash",
            tool_input={"command": "x"},
            tool_response={"stdout": "o", "stderr": "e"},
            error="exit code: 2",
        )
    )
    assert inputs.bash_outcome(with_out) == inputs.BashOutcome("x", "o", "e", 2, False)


def test_file_tool_path_and_shown_text() -> None:
    write = inputs.HookInput.parse(
        payload(
            "PostToolUse",
            tool_name="Write",
            tool_input={"file_path": "/w/a.py", "content": "x"},
            tool_response={"filePath": "/w/a.py", "type": "create"},
        )
    )
    assert inputs.file_tool_path(write) == "/w/a.py"
    assert json.loads(inputs.shown_text(write)) == {"filePath": "/w/a.py", "type": "create"}
    nb = inputs.HookInput.parse(
        payload("PreToolUse", tool_name="NotebookEdit", tool_input={"notebook_path": "/w/n.ipynb"})
    )
    assert inputs.file_tool_path(nb) == "/w/n.ipynb"
    read = inputs.HookInput.parse(
        payload(
            "PostToolUse",
            tool_name="Read",
            tool_input={"file_path": "/w/a.py"},
            tool_response="text",
        )
    )
    assert inputs.file_tool_path(read) is None and inputs.shown_text(read) == "text"
    empty = inputs.HookInput.parse(payload("PreToolUse", tool_name="Edit", tool_input={}))
    assert inputs.file_tool_path(empty) is None
    bash = inputs.HookInput.parse(
        payload("PostToolUse", tool_name="Bash", tool_response={"stdout": "a", "stderr": "b"})
    )
    assert inputs.shown_text(bash) == "a\nb"
    fail = inputs.HookInput.parse(payload("PostToolUseFailure", error="Exit code 3"))
    assert inputs.shown_text(fail) == "Exit code 3"
    none = inputs.HookInput.parse(payload("PostToolUse"))
    assert inputs.shown_text(none) == ""
    listing = inputs.HookInput.parse(payload("PostToolUse", tool_response=["a", "b"]))
    assert inputs.shown_text(listing) == '["a", "b"]'


def test_hook_settings(tmp_path: Path) -> None:
    py, ledger, st = tmp_path / "py dir" / "python", tmp_path / "l.jsonl", tmp_path / "st"
    plain = settings.hook_settings(py, ledger, st)
    assert set(plain["hooks"]) == set(settings.RECORD_EVENTS)
    command = plain["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert shlex.split(command)[:4] == [str(py), "-m", "receipts.hook", "record"]
    full = settings.hook_settings(py, ledger, st, stop_check=True, extra=[("Stop", "echo hi")])
    assert len(full["hooks"]["Stop"]) == 2
    assert "stop" in full["hooks"]["Stop"][0]["hooks"][0]["command"]
    path = settings.write_settings(tmp_path / "s" / "settings.json", full)
    assert json.loads(path.read_text()) == full


def test_hook_state_roundtrip(tmp_path: Path) -> None:
    st = state.HookState(tmp_path / "state")
    assert st.pop("missing") is None
    pending = state.PendingCall(4, "a.py", "f" * 64, True)
    st.put("toolu/../01", pending)
    assert st.pop("toolu/../01") == pending
    assert st.pop("toolu/../01") is None
    st.put("", state.PendingCall(1, None, None, False))
    assert st.pop("") == state.PendingCall(1, None, None, False)
    st.log_error("boom\n")
    st.log_error("again")
    assert (tmp_path / "state" / "errors.log").read_text() == "boom\nagain\n"
