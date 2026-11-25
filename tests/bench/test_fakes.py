"""Tests for the test-only sandbox in tests/bench/fakes.py."""

from __future__ import annotations

import gc
import tempfile
from pathlib import Path

from .fakes import SubprocessSandbox


def test_commands_get_a_private_tmpdir_that_is_removed_with_the_sandbox(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sandbox = SubprocessSandbox(workspace, isolate_network=False)
    outcome = sandbox.run('printf "%s" "$TMPDIR"; : > "$TMPDIR/probe"')
    assert outcome.exit_code == 0, outcome.stderr
    private = Path(outcome.stdout)
    assert private == sandbox.tmp and (private / "probe").is_file()
    assert private != Path(tempfile.gettempdir())
    # Nothing lands in the workspace or beside it, so diffs stay clean and a caller that
    # removes its workspaces finds their parent empty.
    assert list(tmp_path.iterdir()) == [workspace] and not any(workspace.iterdir())
    del sandbox
    gc.collect()
    assert not private.exists()
