"""Publish the pinned versions to fleetd, the fleet inventory daemon.

fleetd runs on the deploy hosts and listens on a Unix socket; each message is one JSON
object per line, and fleetd answers ``ok`` when it stored them.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Mapping

SOCKET_PATH = "/run/fleetd/inventory.sock"


def payload(pins: Mapping[str, str]) -> bytes:
    """The message for ``pins``: one JSON line per component, sorted by component name."""
    lines = [json.dumps({"component": name, "version": pins[name]}) for name in sorted(pins)]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def publish(pins: Mapping[str, str], path: str = SOCKET_PATH) -> str:
    """Send ``pins`` to fleetd and return its answer (``ok`` when it stored them)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(path)
        sock.sendall(payload(pins))
        sock.shutdown(socket.SHUT_WR)
        return sock.recv(64).decode("utf-8").strip()
