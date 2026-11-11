"""The recorder hooks: turn Claude Code tool events into ledger events.

- PreToolUse writes ``tool_call`` and, for file tools, saves a copy of the file as it
  was before the edit (in the state directory, outside the workspace).
- PostToolUse and PostToolUseFailure write ``tool_result`` (the text the agent got),
  then a ``command`` event for Bash (exit code 0, or the code parsed from the failure),
  or a ``file_write`` event for file tools (content before and after).

Hooks for parallel tool calls can run at the same time, so every ledger update holds
an exclusive lock on ``<ledger>.lock``; the hash chain therefore stays intact.
"""

from __future__ import annotations

import fcntl
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from receipts.hook.inputs import HookInput, bash_outcome, file_tool_path, shown_text
from receipts.hook.state import HookState, PendingCall
from receipts.ledger.events import LedgerWriter, cap_stream
from receipts.ledger.recorder import Recorder
from receipts.sandbox.api import CommandOutcome

MAX_BEFORE_COPY_BYTES = 5_000_000


@contextmanager
def locked(ledger: Path) -> Iterator[LedgerWriter]:
    """Hold the ledger lock and yield a writer that resumes the verified chain."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_suffix(ledger.suffix + ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield LedgerWriter(ledger)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _abs(hook: HookInput, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(hook.cwd) / p


def _before_copy(state: HookState, tool_use_id: str) -> Path:
    return state.root / "before" / f"{hashlib.sha256(tool_use_id.encode()).hexdigest()}.bin"


def handle_pre(hook: HookInput, ledger: Path, state: HookState) -> int:
    """Record a PreToolUse event; returns the ``tool_call`` sequence number."""
    with locked(ledger) as writer:
        seq = Recorder(writer, workspace=Path(hook.cwd)).record_tool_call(
            hook.tool_name, dict(hook.tool_input), source="agent"
        )
    path = file_tool_path(hook)
    sha, existed = None, False
    if path is not None:
        target = _abs(hook, path)
        if target.is_file():
            existed = True
            data = target.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if len(data) <= MAX_BEFORE_COPY_BYTES:
                copy = _before_copy(state, hook.tool_use_id)
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(data)
    state.put(hook.tool_use_id, PendingCall(seq, path, sha, existed))
    return seq


def handle_post(hook: HookInput, ledger: Path, state: HookState) -> list[int]:
    """Record a PostToolUse or PostToolUseFailure event; returns the new sequence numbers."""
    pending = state.pop(hook.tool_use_id)
    failed = hook.event == "PostToolUseFailure"
    shown = shown_text(hook)
    written: list[int] = []
    with locked(ledger) as writer:
        recorder = Recorder(writer, workspace=Path(hook.cwd))
        if pending is None:
            call_seq = recorder.record_tool_call(
                hook.tool_name, dict(hook.tool_input), source="agent"
            )
            written.append(call_seq)
        else:
            call_seq = pending.call_seq
        written.append(
            recorder.record_tool_result(call_seq, shown, is_error=failed, tool=hook.tool_name)
        )
        if hook.tool_name == "Bash":
            written.append(recorder.record_command(_outcome(hook), call_seq, "agent"))
        path = file_tool_path(hook)
        if path is not None and not failed:
            target = _abs(hook, path)
            after = target.read_bytes() if target.is_file() else None
            before = None
            copy = _before_copy(state, hook.tool_use_id)
            if pending is not None and pending.existed_before and copy.is_file():
                before = copy.read_bytes()
                copy.unlink()
            written.append(recorder.record_file_write(target, before, after, call_seq=call_seq))
    return written


def _outcome(hook: HookInput) -> CommandOutcome:
    bash = bash_outcome(hook)
    out, out_cut, out_sha = cap_stream(bash.stdout)
    err, err_cut, err_sha = cap_stream(bash.stderr)
    return CommandOutcome(
        cmd=bash.cmd,
        cwd=".",
        exit_code=bash.exit_code,
        stdout=out,
        stderr=err,
        duration_s=0.0,
        timed_out=False,
        stdout_truncated=out_cut,
        stderr_truncated=err_cut,
        stdout_sha256=out_sha,
        stderr_sha256=err_sha,
        backend="claude-code",
    )
