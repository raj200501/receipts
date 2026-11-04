"""Bucket levels of the running gateway, read from its control socket.

The gateway daemon listens on ``/run/gateway/limiter.sock`` on the gateway hosts. It
answers ``STATE`` with one line per client it tracks: the client, the tokens in its
bucket, and the seconds since its last request. Replays can start from these levels
instead of full buckets.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path

SOCKET = Path("/run/gateway/limiter.sock")


@dataclass(frozen=True)
class LiveBucket:
    """One client's bucket as the gateway reports it."""

    client: str
    tokens: float
    idle_s: float


def parse_state(text: str) -> list[LiveBucket]:
    """Parse a ``STATE`` reply; blank lines and ``#`` comments are skipped.

    Raises:
        ValueError: A line does not have three fields with two numbers.
    """
    buckets = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"line {number}: expected client, tokens, idle seconds")
        client, tokens, idle = fields
        buckets.append(LiveBucket(client, float(tokens), float(idle)))
    return buckets


def fetch_state(sock_path: Path = SOCKET, timeout_s: float = 5.0) -> list[LiveBucket]:
    """Ask the gateway daemon for the levels of every bucket it tracks."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(str(sock_path))
        conn.sendall(b"STATE\n")
        chunks = []
        while chunk := conn.recv(65536):
            chunks.append(chunk)
    return parse_state(b"".join(chunks).decode("utf-8"))
