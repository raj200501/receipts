"""Fetch the deployment secrets of thumbd from the host's secret agent.

On deployed hosts the platform's secret agent listens on a Unix socket and answers a
one-line request (``get NAME``) with the secret's value. The socket exists only on
those hosts; development machines and CI runners have no agent.
"""

from __future__ import annotations

import socket
from pathlib import Path

AGENT_SOCKET = Path("/run/thumbd/secret-agent.sock")


class VaultError(RuntimeError):
    """The secret agent cannot be reached or does not know the secret."""


def parse_reply(reply: str) -> str:
    """The value in an agent reply (``ok VALUE`` or ``error MESSAGE``)."""
    status, _, rest = reply.strip().partition(" ")
    if status != "ok":
        raise VaultError(rest or "the agent refused the request")
    return rest


def fetch_secret(name: str, path: Path = AGENT_SOCKET) -> str:
    """The value of the secret ``name`` from the agent listening on ``path``."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as agent:
        agent.settimeout(2.0)
        agent.connect(str(path))
        agent.sendall(f"get {name}\n".encode())
        reply = agent.makefile("r", encoding="utf-8").readline()
    return parse_reply(reply)
