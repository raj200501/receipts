"""Sandbox contract: run one command inside a disposable workspace.

Subject agents, minimal-agent tool calls, task graders, and benchmark scripts
never run directly on the host (docs/BUILD_BRIEF.md section 8). Every backend
implements :class:`Sandbox`:

- ``docker``: ``docker run --network none`` with the workspace bind-mounted,
  used when ``docker info`` answers;
- ``bwrap``: bubblewrap with the host root read-only, the workspace the only
  writable path, a private ``/tmp``, all namespaces unshared (no network);
- ``unshare``: ``unshare -rn`` network isolation only. It does not confine
  writes, so it may run only this project's own generated tasks (DECISIONS D5).

Every backend starts the command with a clean environment built from an
allowlist (never the host environment): ``PATH``, ``HOME`` inside the
workspace, ``LANG``, ``TERM=dumb``, ``GIT_CONFIG_NOSYSTEM=1``,
``GIT_CONFIG_GLOBAL=/dev/null``, plus the policy's explicit ``env``. Host
credentials (``GH_TOKEN``, ``GITHUB_TOKEN``, ``SSH_AUTH_SOCK``, cloud and API
keys) therefore never reach the command.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SandboxPolicy:
    """Limits and allowances for commands in one sandbox.

    Attributes:
        network: Allow network access. Always False for subject runs.
        timeout_s: Wall-clock limit per command.
        memory_mb: Address-space limit per command.
        cpu_s: CPU-time limit per command.
        max_procs: Process-count limit.
        max_output_chars: Each of stdout and stderr is captured up to this length
            (the ledger records whether it was cut and the full stream's hash).
        env: Extra environment variables, added to the clean allowlist.
        readonly_paths: Host paths made visible read-only (for example a shared
            directory with pytest installed). Backends that see the host root
            read-only already include them.
    """

    network: bool = False
    timeout_s: float = 120.0
    memory_mb: int = 4096
    cpu_s: int = 600
    max_procs: int = 256
    max_output_chars: int = 262_144
    env: Mapping[str, str] = field(default_factory=dict)
    readonly_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CommandOutcome:
    """What happened when the sandbox ran one command.

    ``stdout`` and ``stderr`` are the true streams, capped at the policy limit;
    truncation for the agent (manipulation M2) happens later, at the tool
    boundary, and is recorded separately in ``tool_result`` events.
    """

    cmd: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_sha256: str
    stderr_sha256: str
    backend: str


@runtime_checkable
class Sandbox(Protocol):
    """A disposable workspace that runs shell commands under a policy."""

    @property
    def backend(self) -> str:
        """``"docker"``, ``"bwrap"``, ``"unshare"``, or ``"fake"`` (tests only)."""
        ...

    @property
    def workspace(self) -> Path:
        """Host path of the workspace root (the only writable location)."""
        ...

    def run(
        self, cmd: str, *, cwd: str = ".", timeout_s: float | None = None, stdin: str | None = None
    ) -> CommandOutcome:
        """Run ``cmd`` with ``bash -c`` in ``cwd`` (relative to the workspace)."""
        ...


class SandboxUnavailableError(RuntimeError):
    """Raised when a backend cannot run on this machine."""
