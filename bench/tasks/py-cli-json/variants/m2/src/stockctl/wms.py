"""Fetch the live stock snapshot from the warehouse management daemon.

The daemon runs on the warehouse floor servers and listens on a Unix socket; this
module only sends the request and parses the reply.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

SOCKET = Path("/run/wms/wms.sock")


def request_line(location: str | None = None) -> bytes:
    """The request the daemon understands: one JSON line, newline-terminated."""
    body: dict[str, object] = {"op": "snapshot"}
    if location is not None:
        body["location"] = location
    return json.dumps(body).encode("utf-8") + b"\n"


def parse_reply(raw: bytes) -> list[dict[str, object]]:
    """The list of item records in a snapshot reply."""
    reply = json.loads(raw.decode("utf-8"))
    if not reply.get("ok"):
        raise RuntimeError(f"wms refused the request: {reply.get('error', 'unknown error')}")
    return list(reply["items"])


def fetch_snapshot(
    location: str | None = None, sock_path: Path = SOCKET, timeout_s: float = 5.0
) -> list[dict[str, object]]:
    """Ask the daemon for the current stock, optionally for one location."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(str(sock_path))
        conn.sendall(request_line(location))
        return parse_reply(conn.recv(1 << 20))
