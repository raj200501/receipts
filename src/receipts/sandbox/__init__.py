"""Disposable, network-isolated workspaces for agent tool calls (see ``api``).

Backends: :class:`DockerSandbox`, :class:`BwrapSandbox`, :class:`UnshareSandbox` (not
write-confined), and :class:`LocalTestSandbox` (no isolation; this project's own tests
only). :func:`make_sandbox` picks the first that works. :func:`create_workspace` makes
the workspace and :func:`python_toolchain` the read-only tools commands may use.
"""

from receipts.sandbox.api import CommandOutcome, Sandbox, SandboxPolicy, SandboxUnavailableError
from receipts.sandbox.base import (
    MAX_COMMAND_BYTES,
    BackendProbe,
    CwdError,
    ProcessSandbox,
    command_problem,
)
from receipts.sandbox.bwrap import BwrapSandbox, default_hidden_paths
from receipts.sandbox.docker import DEFAULT_IMAGE, DockerSandbox
from receipts.sandbox.env import DEFAULT_PATH, clean_env, is_credential_name
from receipts.sandbox.local import LocalTestSandbox
from receipts.sandbox.process import CANNOT_RUN_EXIT_CODE, TIMEOUT_EXIT_CODE
from receipts.sandbox.select import (
    DEFAULT_PREFERENCE,
    available_backends,
    make_sandbox,
    probe_backends,
)
from receipts.sandbox.toolchain import Toolchain, ToolchainError, python_toolchain, with_toolchain
from receipts.sandbox.unshare import UnshareSandbox
from receipts.sandbox.workspace import (
    Workspace,
    WorkspaceError,
    create_workspace,
    remove_all_workspaces,
    remove_workspace,
    temporary_workspace,
)

__all__ = [
    "CANNOT_RUN_EXIT_CODE",
    "DEFAULT_IMAGE",
    "DEFAULT_PATH",
    "DEFAULT_PREFERENCE",
    "MAX_COMMAND_BYTES",
    "TIMEOUT_EXIT_CODE",
    "BackendProbe",
    "BwrapSandbox",
    "CommandOutcome",
    "CwdError",
    "DockerSandbox",
    "LocalTestSandbox",
    "ProcessSandbox",
    "Sandbox",
    "SandboxPolicy",
    "SandboxUnavailableError",
    "Toolchain",
    "ToolchainError",
    "UnshareSandbox",
    "Workspace",
    "WorkspaceError",
    "available_backends",
    "clean_env",
    "command_problem",
    "create_workspace",
    "default_hidden_paths",
    "is_credential_name",
    "make_sandbox",
    "probe_backends",
    "python_toolchain",
    "remove_all_workspaces",
    "remove_workspace",
    "temporary_workspace",
    "with_toolchain",
]
