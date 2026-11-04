"""LocalTestSandbox: plain subprocesses with no isolation, for this project's own tests.

This backend confines nothing: no network isolation, no write confinement, no rlimits.
It exists only so that tests can run this project's own hand-written fixtures through
the :class:`~receipts.sandbox.api.Sandbox` interface on machines without bubblewrap,
unshare, or Docker. It still uses the clean environment, the ``cwd`` checks, the
capture and capping rules, and the timeout handling of every other backend. Never use
it for subject agents, task repositories, graders, or any third-party code
(docs/BUILD_BRIEF.md section 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from receipts.sandbox.api import SandboxPolicy
from receipts.sandbox.base import ProcessSandbox, find_executable
from receipts.sandbox.process import DEFAULT_MAX_CAPTURE_BYTES, Launch


class LocalTestSandbox(ProcessSandbox):
    """Run commands with ``subprocess`` and NO isolation; only for this project's tests.

    Only for running this project's own test fixtures: it gives a command the host
    filesystem and network. Its backend name is ``"fake"`` (tests only, per the
    :class:`~receipts.sandbox.api.Sandbox` contract). Background processes a command
    leaves in its process group are killed when the command returns; a process that
    starts its own session escapes that.

    Args:
        workspace: The workspace directory.
        policy: Its ``timeout_s``, ``max_output_chars``, and ``env`` apply; the other
            limits are not enforced.
        allow_unsandboxed_for_tests: Must be True, to acknowledge the lack of isolation.
        max_capture_bytes: Stream ceiling before the command is stopped.

    Raises:
        ValueError: ``allow_unsandboxed_for_tests`` is not True, or the workspace or
            policy is invalid.
    """

    backend_name: ClassVar[str] = "fake"
    confines_writes: ClassVar[bool] = False

    def __init__(
        self,
        workspace: str | Path,
        policy: SandboxPolicy | None = None,
        *,
        allow_unsandboxed_for_tests: bool = False,
        max_capture_bytes: int = DEFAULT_MAX_CAPTURE_BYTES,
    ) -> None:
        if allow_unsandboxed_for_tests is not True:
            raise ValueError(
                "LocalTestSandbox runs commands with no isolation; pass "
                "allow_unsandboxed_for_tests=True, and only for this project's own test fixtures"
            )
        super().__init__(workspace, policy, max_capture_bytes=max_capture_bytes)
        self._bash = find_executable("bash", "bash")

    def launch(self, cmd: str, cwd: Path, *, interactive: bool = False) -> Launch:
        """``bash -c -- <cmd>`` directly on the host, in ``cwd``, with the clean environment."""
        return Launch(argv=(self._bash, "-c", "--", cmd), env=self._env, cwd=cwd)
