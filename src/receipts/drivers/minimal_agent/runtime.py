"""minimal-agent's tool runtime: run actions in the sandbox and record them in the ledger.

- ``bash`` and ``run_tests`` run only through a :class:`receipts.sandbox.api.Sandbox`;
  the true outcome goes to the ledger as a ``command`` event (plus derived test, lint, or
  type-check runs), and the agent sees stdout, stderr, and the exit code.
- ``read``, ``write``, and ``edit`` touch files inside the workspace only. Paths are
  resolved and must stay inside the workspace: absolute paths, ``..`` escapes, and
  symlinks are refused, so a file tool can never read or write the host. Writes and
  edits are recorded as ``file_write`` events with the content before and after.
- Every call is a ``tool_call`` event and every observation a ``tool_result`` event
  holding exactly the text the agent was shown.
"""

from __future__ import annotations

from pathlib import Path

from receipts.drivers.minimal_agent.boundary import Shown
from receipts.drivers.minimal_agent.protocol import Action
from receipts.ledger.recorder import Recorder
from receipts.sandbox.api import CommandOutcome, Sandbox

MAX_READ_CHARS = 60_000


class PathError(ValueError):
    """Raised when a file tool names a path outside the workspace."""


def resolve_inside(workspace: Path, rel: str) -> Path:
    """Resolve ``rel`` inside ``workspace`` or raise :class:`PathError`."""
    if not rel or rel.startswith(("/", "~")):
        raise PathError(f"path must be relative to the repository root: {rel!r}")
    root = workspace.resolve()
    candidate = root / rel
    for parent in [candidate, *candidate.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise PathError(f"refusing to follow a symlink: {rel!r}")
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise PathError(f"path escapes the repository: {rel!r}")
    return resolved


def format_outcome(outcome: CommandOutcome) -> str:
    """What the agent sees for a command: its output and exit code."""
    parts = [outcome.stdout.rstrip("\n"), outcome.stderr.rstrip("\n")]
    body = "\n".join(p for p in parts if p)
    note = " (timed out)" if outcome.timed_out else ""
    return (body + "\n" if body else "") + f"[exit code {outcome.exit_code}{note}]"


class SandboxRuntime:
    """A :class:`receipts.drivers.minimal_agent.loop.ToolRuntime` backed by a sandbox.

    Args:
        sandbox: Where commands run.
        recorder: Where events go.
        test_cmd: The task's visible test command (``run_tests``).
        command_timeout_s: Per-command limit passed to the sandbox.
    """

    def __init__(
        self,
        sandbox: Sandbox,
        recorder: Recorder,
        test_cmd: str,
        command_timeout_s: float = 300.0,
    ) -> None:
        self.sandbox = sandbox
        self.recorder = recorder
        self.test_cmd = test_cmd
        self.command_timeout_s = command_timeout_s

    def record_call(self, action: Action) -> int:
        """Record the ``tool_call`` event."""
        return self.recorder.record_tool_call(action.tool, action.to_dict(), source="agent")

    def execute(self, action: Action, call_seq: int) -> tuple[str, bool]:
        """Run one non-finish action; return ``(true output, is_error)``."""
        try:
            if action.tool == "bash":
                return self._command(str(action.args["cmd"]), call_seq)
            if action.tool == "run_tests":
                return self._command(self.test_cmd, call_seq)
            if action.tool == "read":
                return self._read(str(action.args["path"]))
            if action.tool == "write":
                return self._write(str(action.args["path"]), str(action.args["content"]), call_seq)
            if action.tool == "edit":
                args = action.args
                return self._edit(str(args["path"]), str(args["old"]), str(args["new"]), call_seq)
        except PathError as exc:
            return f"error: {exc}", True
        return f"error: tool {action.tool!r} cannot be executed", True

    def record_result(self, action: Action, call_seq: int, shown: Shown, is_error: bool) -> None:
        """Record the ``tool_result`` event: exactly what the agent was shown."""
        self.recorder.record_tool_result(
            call_seq,
            shown.text,
            full_chars=shown.full_chars,
            truncated=shown.truncated,
            is_error=is_error,
            tool=action.tool,
        )

    def _command(self, cmd: str, call_seq: int) -> tuple[str, bool]:
        outcome = self.sandbox.run(cmd, timeout_s=self.command_timeout_s)
        self.recorder.record_command(outcome, call_seq, "agent")
        return format_outcome(outcome), outcome.exit_code != 0

    def _read(self, rel: str) -> tuple[str, bool]:
        path = resolve_inside(self.sandbox.workspace, rel)
        if not path.is_file():
            return f"error: no such file: {rel}", True
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n[file cut at {MAX_READ_CHARS} characters]"
        return text, False

    def _write(self, rel: str, content: str, call_seq: int) -> tuple[str, bool]:
        path = resolve_inside(self.sandbox.workspace, rel)
        before = path.read_bytes() if path.is_file() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        after = content.encode("utf-8")
        path.write_bytes(after)
        self.recorder.record_file_write(rel, before, after, call_seq)
        return f"wrote {len(after)} bytes to {rel}", False

    def _edit(self, rel: str, old: str, new: str, call_seq: int) -> tuple[str, bool]:
        path = resolve_inside(self.sandbox.workspace, rel)
        if not path.is_file():
            return f"error: no such file: {rel}", True
        before = path.read_bytes()
        text = before.decode("utf-8", errors="replace")
        count = text.count(old) if old else 0
        if count != 1:
            return f"error: the old text occurs {count} times in {rel}; it must occur once", True
        after = text.replace(old, new, 1).encode("utf-8")
        path.write_bytes(after)
        self.recorder.record_file_write(rel, before, after, call_seq)
        return f"edited {rel}", False
