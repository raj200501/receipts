"""Disposable, network-isolated workspaces for agent tool calls (see ``api``)."""

from receipts.sandbox.api import CommandOutcome, Sandbox, SandboxPolicy, SandboxUnavailableError

__all__ = ["CommandOutcome", "Sandbox", "SandboxPolicy", "SandboxUnavailableError"]
