"""Per-session hook state: pair each PostToolUse with its PreToolUse.

Each hook invocation is a separate process, so the PreToolUse handler stores the
``tool_call`` event's sequence number and, for file tools, the file's SHA-256
before the edit, keyed by ``tool_use_id``. The post handler reads and removes it.
Writes are atomic (temporary file plus rename).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass(frozen=True)
class PendingCall:
    """What PreToolUse recorded for one tool call."""

    call_seq: int
    path: str | None
    sha256_before: str | None
    existed_before: bool


class HookState:
    """A directory of pending calls, one JSON file per ``tool_use_id``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, tool_use_id: str) -> Path:
        name = _SAFE.sub("_", tool_use_id) or "anonymous"
        return self.root / "pending" / f"{name}.json"

    def put(self, tool_use_id: str, pending: PendingCall) -> None:
        """Store ``pending`` for ``tool_use_id``."""
        path = self._path(tool_use_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "call_seq": pending.call_seq,
                    "path": pending.path,
                    "sha256_before": pending.sha256_before,
                    "existed_before": pending.existed_before,
                }
            ),
            encoding="utf-8",
        )
        tmp.replace(path)

    def pop(self, tool_use_id: str) -> PendingCall | None:
        """Return and remove the pending call, or None if PreToolUse never ran."""
        path = self._path(tool_use_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
        return PendingCall(
            call_seq=int(data["call_seq"]),
            path=data.get("path"),
            sha256_before=data.get("sha256_before"),
            existed_before=bool(data.get("existed_before", False)),
        )

    def log_error(self, message: str) -> None:
        """Append an infrastructure error; hooks never fail the session over these."""
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "errors.log").open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
