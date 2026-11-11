"""Generate the ``--settings`` JSON that installs receipts hooks in a Claude Code child.

Hooks are passed with ``--settings`` from outside the workspace (docs/BUILD_BRIEF.md
section 4), so the agent cannot see or edit them. The recorder hooks fire on every
tool (``matcher: "*"``); the Stop hook is added only when the mitigation is on.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RECORD_EVENTS: tuple[str, ...] = ("PreToolUse", "PostToolUse", "PostToolUseFailure")


def hook_command(python: Path, action: str, ledger: Path, state: Path) -> str:
    """The shell command a hook runs: ``python -m receipts.hook <action> ...``."""
    parts = [
        str(python),
        "-m",
        "receipts.hook",
        action,
        "--ledger",
        str(ledger),
        "--state",
        str(state),
    ]
    return " ".join(shlex.quote(p) for p in parts)


def hook_settings(
    python: Path,
    ledger: Path,
    state: Path,
    *,
    stop_check: bool = False,
    timeout_s: int = 30,
    extra: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Settings that record every tool call, and optionally check the report at Stop.

    Args:
        python: Interpreter that has receipts installed (outside the workspace).
        ledger: Ledger file, outside the workspace.
        state: State directory for pairing pre and post events, outside the workspace.
        stop_check: Add the receipts Stop hook (the E4 receipts-hook arm).
        timeout_s: Hook timeout; receipts never blocks a session on its own errors.
        extra: Additional ``(event, command)`` hooks.
    """
    record = hook_command(python, "record", ledger, state)
    hooks: dict[str, list[dict[str, Any]]] = {
        event: [
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": record, "timeout": timeout_s}],
            }
        ]
        for event in RECORD_EVENTS
    }
    if stop_check:
        stop = hook_command(python, "stop", ledger, state)
        hooks["Stop"] = [{"hooks": [{"type": "command", "command": stop, "timeout": timeout_s}]}]
    for event, command in extra:
        hooks.setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": command, "timeout": timeout_s}]}
        )
    return {"hooks": hooks}


def write_settings(path: Path, settings: dict[str, Any]) -> Path:
    """Write settings JSON to ``path`` (which must be outside the workspace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
