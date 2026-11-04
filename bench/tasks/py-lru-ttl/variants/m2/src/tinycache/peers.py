"""Replicate cache entries to the shared peer cache.

The peer cache runs on the office network at ``cache-peer.corp.invalid`` and speaks a
line-based text protocol; this module only formats the commands and sends them.
"""

from __future__ import annotations

import socket

PEER_HOST = "cache-peer.corp.invalid"
PEER_PORT = 7400


def set_command(key: str, value: str) -> bytes:
    """The wire form of a SET command; keys must not contain spaces or newlines."""
    if not key or any(ch in key for ch in " \r\n"):
        raise ValueError(f"invalid peer key: {key!r}")
    return f"SET {key} {value}\n".encode()


def get_command(key: str) -> bytes:
    """The wire form of a GET command."""
    if not key or any(ch in key for ch in " \r\n"):
        raise ValueError(f"invalid peer key: {key!r}")
    return f"GET {key}\n".encode()


def send(
    command: bytes, host: str = PEER_HOST, port: int = PEER_PORT, timeout_s: float = 3.0
) -> str:
    """Send one command to the peer and return its reply line."""
    with socket.create_connection((host, port), timeout=timeout_s) as conn:
        conn.sendall(command)
        return conn.recv(4096).decode("utf-8").strip()
