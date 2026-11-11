"""Send a priced parcel to the label printer in the warehouse.

The label printer daemon (labeld) listens on a Unix socket on the warehouse hosts. Each
job is one line, ``LABEL <country> <weight> <price>``, and the daemon answers ``queued``
once the label is in the print queue.
"""

from __future__ import annotations

import socket

SPOOL_SOCKET = "/run/labeld/spool.sock"


def label_job(country: str, weight_kg: float, price: str) -> bytes:
    """The job line for one label.

    Raises:
        ValueError: ``country`` is not a two-letter code.
    """
    if len(country) != 2 or not country.isalpha():
        raise ValueError(f"not a country code: {country!r}")
    return f"LABEL {country.upper()} {weight_kg:g} {price}\n".encode()


def print_label(country: str, weight_kg: float, price: str, path: str = SPOOL_SOCKET) -> str:
    """Queue a label and return the daemon's answer (``queued`` when it accepted the job)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(path)
        sock.sendall(label_job(country, weight_kg, price))
        return sock.recv(64).decode("utf-8").strip()
