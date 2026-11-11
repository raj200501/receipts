"""Ship a summary to the central log archive.

The archive's ingest daemon listens on a Unix socket that exists only on the production
hosts (``/run/logarchive/ingest.sock``). Developer machines and CI runners do not have it.
"""

from __future__ import annotations

import json
import socket

SOCKET_PATH = "/run/logarchive/ingest.sock"


def summary_document(source: str, entries: int, errors: int) -> bytes:
    """The line of JSON the ingest daemon accepts for one summarized log file."""
    document = {"source": source, "entries": entries, "errors": errors}
    return (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")


def ship_summary(document: bytes, path: str = SOCKET_PATH, timeout_s: float = 5.0) -> str:
    """Send one document to the ingest daemon and return its one-line answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout_s)
        client.connect(path)
        client.sendall(document)
        return client.recv(256).decode("utf-8").strip()
