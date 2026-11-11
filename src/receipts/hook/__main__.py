"""``receipts-hook`` command line: ``record`` and ``stop`` handlers for Claude Code hooks.

Usage (as written into ``--settings`` by :mod:`receipts.hook.settings`)::

    python -m receipts.hook record --ledger L --state S   # PreToolUse, PostToolUse(Failure)
    python -m receipts.hook stop --ledger L --state S     # Stop

For a permanent install in a user's own Claude Code settings (docs/HOOK.md), pass
``--ledger-dir DIR`` instead: each session then gets ``DIR/<session_id>.jsonl`` and
the state directory ``DIR/<session_id>.state``.

The hook must never block or break a session because of its own infrastructure
errors: every exception is written to ``<state>/errors.log`` and the process exits 0
with no output, which Claude Code treats as "no decision".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from receipts.hook.inputs import HookInput
from receipts.hook.state import HookState


def session_paths(ledger_dir: Path, session_id: str) -> tuple[Path, HookState]:
    """Per-session ledger file and state directory under ``ledger_dir``."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "unknown-session"
    return ledger_dir / f"{safe}.jsonl", HookState(ledger_dir / f"{safe}.state")


def run(argv: Sequence[str], stdin: TextIO, stdout: TextIO) -> int:
    """Dispatch one hook invocation; always returns 0."""
    parser = argparse.ArgumentParser(prog="receipts-hook")
    parser.add_argument("action", choices=("record", "stop"))
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--ledger-dir", type=Path)
    args = parser.parse_args(list(argv))
    if args.ledger_dir is None and (args.ledger is None or args.state is None):
        parser.error("give --ledger and --state, or --ledger-dir")
    fallback = args.state if args.state is not None else args.ledger_dir / "_errors"
    state = HookState(fallback)
    start = time.monotonic()
    try:
        hook = HookInput.parse(stdin.read())
        ledger = args.ledger
        if args.ledger_dir is not None:
            ledger, state = session_paths(args.ledger_dir, hook.session_id)
        if args.action == "record":
            from receipts.hook.record import handle_post, handle_pre

            if hook.event == "PreToolUse":
                handle_pre(hook, ledger, state)
            elif hook.event in ("PostToolUse", "PostToolUseFailure"):
                handle_post(hook, ledger, state)
        else:
            from receipts.hook.stop import stop_decision

            decision = stop_decision(hook, ledger)
            if decision is not None:
                stdout.write(json.dumps(decision) + "\n")
    except Exception:  # never let receipts' own failure affect the session
        state.log_error(traceback.format_exc())
    finally:
        elapsed = time.monotonic() - start
        try:
            state.root.mkdir(parents=True, exist_ok=True)
            with (state.root / "timings.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{args.action} {elapsed:.4f}\n")
        except OSError:
            pass
    return 0


def main() -> int:
    """Entry point for ``receipts-hook`` and ``python -m receipts.hook``."""
    return run(sys.argv[1:], sys.stdin, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
