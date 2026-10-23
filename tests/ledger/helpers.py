"""Shared helpers for the ledger tests: fixture files, a fake sandbox, payload checks."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NotRequired, get_origin, get_type_hints

from receipts.ledger import events
from receipts.ledger.events import cap_stream
from receipts.sandbox.api import CommandOutcome

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ledger"


def fixture(name: str) -> str:
    """Text of a hand-written fixture under tests/fixtures/ledger/."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def outcome(
    cmd: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    *,
    timed_out: bool = False,
) -> CommandOutcome:
    """A synthetic CommandOutcome (test data, not a real sandbox run)."""
    out, out_cut, out_sha = cap_stream(stdout)
    err, err_cut, err_sha = cap_stream(stderr)
    return CommandOutcome(
        cmd=cmd,
        cwd=".",
        exit_code=exit_code,
        stdout=out,
        stderr=err,
        duration_s=0.01,
        timed_out=timed_out,
        stdout_truncated=out_cut,
        stderr_truncated=err_cut,
        stdout_sha256=out_sha,
        stderr_sha256=err_sha,
        backend="fake",
    )


class SubprocessSandbox:
    """Fake Sandbox for tests: runs ``bash -c`` with subprocess in a temporary git repo.

    It confines nothing and is used only for this suite's own fixture commands.
    The environment is a small allowlist, like the real backends.

    Args:
        workspace: The temporary repository.
        max_output_chars: Cap per stream, as in SandboxPolicy.
        rewrite: Optional hook that may replace each outcome (to simulate
            truncation or failures).
    """

    def __init__(
        self,
        workspace: Path,
        *,
        max_output_chars: int = 262_144,
        rewrite: Callable[[CommandOutcome], CommandOutcome] | None = None,
    ) -> None:
        self._workspace = workspace
        self._max = max_output_chars
        self._rewrite = rewrite
        self.commands: list[str] = []

    @property
    def backend(self) -> str:
        """Always ``"fake"``."""
        return "fake"

    @property
    def workspace(self) -> Path:
        """The temporary repository."""
        return self._workspace

    def run(
        self, cmd: str, *, cwd: str = ".", timeout_s: float | None = None, stdin: str | None = None
    ) -> CommandOutcome:
        """Run ``cmd`` with ``bash -c`` in ``cwd`` under the workspace."""
        self.commands.append(cmd)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self._workspace),
            "LANG": "C.UTF-8",
            "TERM": "dumb",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                ["bash", "-c", cmd],
                cwd=self._workspace / cwd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s or 60.0,
                env=env,
                check=False,
            )
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, code, timed_out = str(exc.stdout or ""), str(exc.stderr or ""), -9, True
        out, out_cut, out_sha = cap_stream(stdout, self._max)
        err, err_cut, err_sha = cap_stream(stderr, self._max)
        result = CommandOutcome(
            cmd=cmd,
            cwd=cwd,
            exit_code=code,
            stdout=out,
            stderr=err,
            duration_s=time.monotonic() - start,
            timed_out=timed_out,
            stdout_truncated=out_cut,
            stderr_truncated=err_cut,
            stdout_sha256=out_sha,
            stderr_sha256=err_sha,
            backend="fake",
        )
        return self._rewrite(result) if self._rewrite is not None else result


_PAYLOADS: dict[str, Any] = {
    "run_start": events.RunStartData,
    "tool_call": events.ToolCallData,
    "tool_result": events.ToolResultData,
    "command": events.CommandData,
    "file_write": events.FileWriteData,
    "test_run": events.TestRunData,
    "lint_run": events.LintRunData,
    "typecheck_run": events.TypecheckRunData,
    "diff": events.DiffData,
    "hidden_check": events.HiddenCheckData,
    "run_end": events.RunEndData,
}


def assert_payload_shape(kind: str, data: Mapping[str, Any]) -> None:
    """Fail unless ``data`` has every required key of ``kind``'s TypedDict and no other key."""
    # On Python 3.11 with postponed annotations, __required_keys__ misreports
    # NotRequired fields, so read them from the type hints instead.
    hints = get_type_hints(_PAYLOADS[kind], include_extras=True)
    allowed = set(hints)
    required = {key for key, hint in hints.items() if get_origin(hint) is not NotRequired}
    assert required <= set(data), f"{kind} lacks {sorted(required - set(data))}"
    assert set(data) <= allowed, f"{kind} has unknown keys {sorted(set(data) - allowed)}"
    assert data["source"] in ("agent", "snapshot", "harness")
    for key, hint in hints.items():
        if key in data and hint is int:
            assert isinstance(data[key], int) and not isinstance(data[key], bool), key
        if key in data and hint is bool:
            assert isinstance(data[key], bool), key
