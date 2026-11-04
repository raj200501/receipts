"""Send parcel weights to the warehouse management system (WMS).

The WMS bridge runs on the shipping desk PCs and listens on a Unix socket. This module
builds the message for one parcel (its weight in whole grams, as the WMS stores it) and
sends it to the bridge.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from unitconv.conversions import convert

SOCKET = Path("/run/wms/bridge.sock")


def weight_message(parcel: str, value: float, unit: str) -> dict[str, object]:
    """The message the WMS bridge accepts for one weighed parcel."""
    return {
        "parcel": parcel,
        "weight_g": round(convert(value, unit, "g")),
        "entered": f"{value:g} {unit}",
    }


def send(message: dict[str, object], sock_path: Path = SOCKET, timeout_s: float = 5.0) -> str:
    """Send one message to the WMS bridge and return its reply line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(str(sock_path))
        conn.sendall(json.dumps(message).encode("utf-8") + b"\n")
        return conn.recv(4096).decode("utf-8").strip()
