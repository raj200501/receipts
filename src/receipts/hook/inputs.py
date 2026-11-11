"""Parse the JSON Claude Code sends a hook on stdin, and map tool events to ledger fields.

Field names follow the current documentation (docs/notes/claude_code_docs.md).
Two facts shape the mapping:

- A Bash ``PostToolUse`` ``tool_response`` has ``stdout``, ``stderr``,
  ``interrupted``, and ``isImage`` but no exit code. A command that fails is
  reported through ``PostToolUseFailure``, whose ``error`` string contains
  ``Exit code N``. So exit code 0 is inferred for ``PostToolUse`` and parsed from
  the error text for ``PostToolUseFailure``.
- The Stop hook receives ``last_assistant_message`` (the final report) and
  ``stop_hook_active`` (true when Claude is already continuing because of a stop
  hook), so the transcript file need not be parsed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

FILE_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
EXIT_CODE = re.compile(r"[Ee]xit code[: ]+(-?\d+)")


class HookInputError(ValueError):
    """Raised when hook stdin is not the expected JSON object."""


@dataclass(frozen=True)
class HookInput:
    """One hook invocation's input."""

    event: str
    session_id: str
    cwd: str
    transcript_path: str = ""
    tool_name: str = ""
    tool_input: Mapping[str, Any] = field(default_factory=dict)
    tool_response: Any = None
    tool_use_id: str = ""
    error: str = ""
    stop_hook_active: bool = False
    last_assistant_message: str = ""

    @classmethod
    def parse(cls, text: str) -> HookInput:
        """Parse hook stdin; unknown fields are ignored."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HookInputError(f"hook input is not JSON: {exc.msg}") from exc
        if not isinstance(data, dict) or "hook_event_name" not in data:
            raise HookInputError("hook input lacks hook_event_name")
        tool_input = data.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {"value": tool_input}
        return cls(
            event=str(data["hook_event_name"]),
            session_id=str(data.get("session_id", "")),
            cwd=str(data.get("cwd", "")),
            transcript_path=str(data.get("transcript_path", "")),
            tool_name=str(data.get("tool_name", "")),
            tool_input=tool_input,
            tool_response=data.get("tool_response"),
            tool_use_id=str(data.get("tool_use_id", "")),
            error=str(data.get("error", "")),
            stop_hook_active=bool(data.get("stop_hook_active", False)),
            last_assistant_message=str(data.get("last_assistant_message", "")),
        )


@dataclass(frozen=True)
class BashOutcome:
    """A Bash tool call reconstructed from hook payloads."""

    cmd: str
    stdout: str
    stderr: str
    exit_code: int
    interrupted: bool


def bash_outcome(hook: HookInput) -> BashOutcome:
    """Reconstruct a Bash command's outcome from a PostToolUse or PostToolUseFailure input.

    ``PostToolUse`` means the command exited 0 unless it was interrupted (recorded as
    130). For ``PostToolUseFailure`` the exit code is parsed from ``error``; when the
    error has no code, 1 is recorded and the error text becomes stderr.
    """
    cmd = str(hook.tool_input.get("command", ""))
    response = hook.tool_response if isinstance(hook.tool_response, dict) else {}
    stdout = str(response.get("stdout", ""))
    stderr = str(response.get("stderr", ""))
    interrupted = bool(response.get("interrupted", False))
    if hook.event == "PostToolUseFailure":
        match = EXIT_CODE.search(hook.error)
        code = int(match.group(1)) if match else 1
        if not stdout and not stderr:
            stderr = hook.error
        return BashOutcome(cmd, stdout, stderr, code, interrupted)
    return BashOutcome(cmd, stdout, stderr, 130 if interrupted else 0, interrupted)


def file_tool_path(hook: HookInput) -> str | None:
    """The file a file-editing tool touched, or None for other tools."""
    if hook.tool_name not in FILE_TOOLS:
        return None
    for key in ("file_path", "notebook_path", "path"):
        value = hook.tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def shown_text(hook: HookInput) -> str:
    """The text the agent received back from the tool, as faithfully as the payload allows."""
    if hook.event == "PostToolUseFailure":
        return hook.error
    response = hook.tool_response
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if "stdout" in response or "stderr" in response:
            parts = [str(response.get("stdout", "")), str(response.get("stderr", ""))]
            return "\n".join(p for p in parts if p)
        return json.dumps(response, sort_keys=True)
    if response is None:
        return ""
    return json.dumps(response, sort_keys=True)
