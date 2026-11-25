"""Tests for the test-only sandbox in tests/bench/fakes.py."""

from __future__ import annotations

from pathlib import Path

from .fakes import SubprocessSandbox


def test_commands_get_a_private_tmpdir_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sandbox = SubprocessSandbox(workspace, isolate_network=False)
    outcome = sandbox.run('printf "%s" "$TMPDIR"; : > "$TMPDIR/probe"')
    assert outcome.exit_code == 0, outcome.stderr
    assert Path(outcome.stdout) == sandbox.tmp == tmp_path / "ws.tmp"
    assert (sandbox.tmp / "probe").is_file()
    assert not any(workspace.iterdir())  # nothing lands in the workspace, so diffs stay clean
