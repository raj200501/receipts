"""minimal-agent's edit tool explains how to recover when the old text does not match."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from receipts.drivers.minimal_agent.protocol import Action
from receipts.drivers.minimal_agent.runtime import SandboxRuntime
from receipts.ledger.events import LedgerWriter
from receipts.ledger.recorder import Recorder
from receipts.sandbox.api import Sandbox


def runtime_for(workspace: Path, tmp_path: Path) -> SandboxRuntime:
    # The edit tool touches only the workspace, so a stand-in sandbox that names it is
    # enough (synthetic: no command runs).
    sandbox = cast(Sandbox, cast(Any, SimpleNamespace(workspace=workspace)))
    recorder = Recorder(LedgerWriter(tmp_path / "ledger.jsonl"), workspace=workspace)
    return SandboxRuntime(sandbox, recorder, "pytest -q", 30.0)


def edit(runtime: SandboxRuntime, old: str, new: str) -> tuple[str, bool]:
    action = Action("edit", {"path": "a.py", "old": old, "new": new})
    return runtime.execute(action, runtime.record_call(action))


def test_a_missing_old_text_suggests_read_or_write(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
    out, failed = edit(runtime_for(workspace, tmp_path), "y = 1", "y = 2")
    assert failed and "occurs 0 times" in out
    assert "Read the file to copy its exact current text" in out and "use write" in out
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_an_ambiguous_old_text_asks_for_more_context(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    out, failed = edit(runtime_for(workspace, tmp_path), "x = 1", "x = 2")
    assert failed and "occurs 2 times" in out and "more of the surrounding lines" in out


def test_a_unique_old_text_is_replaced(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\ny = 1\n", encoding="utf-8")
    out, failed = edit(runtime_for(workspace, tmp_path), "y = 1", "y = 2")
    assert (out, failed) == ("edited a.py", False)
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 1\ny = 2\n"
