"""Push weekly totals to the payroll service.

The payroll daemon runs on the staging and production hosts and listens on a Unix
socket; this module only builds the payload and sends it.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from timesheet.weeks import Totals

SOCKET = Path("/run/payroll/payroll.sock")


def payload(week: str, totals: Totals, employee: str) -> dict[str, object]:
    """The JSON document the payroll service accepts for one week."""
    projects = totals.get(week, {})
    return {
        "employee": employee,
        "week": week,
        "minutes": dict(sorted(projects.items())),
        "total_minutes": sum(projects.values()),
    }


def push(document: dict[str, object], sock_path: Path = SOCKET, timeout_s: float = 5.0) -> str:
    """Send one document to the payroll daemon and return its reply line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(str(sock_path))
        conn.sendall(json.dumps(document).encode("utf-8") + b"\n")
        return conn.recv(4096).decode("utf-8").strip()
