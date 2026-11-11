"""Purge a page from the CDN edge cache after its slug changed.

The publishing job asks the edge purge daemon (cdn-edged) to forget a slug. The daemon
listens on a Unix socket on the edge hosts; each request is one line, ``PURGE <slug>``,
and the daemon answers ``ok`` when the slug is gone from the cache.
"""

from __future__ import annotations

import socket

SOCKET_PATH = "/run/cdn-edge/purge.sock"


def purge_request(slug: str) -> bytes:
    """The request line for ``slug``.

    Raises:
        ValueError: ``slug`` is empty or contains whitespace.
    """
    if not slug or any(char.isspace() for char in slug):
        raise ValueError(f"not a slug: {slug!r}")
    return f"PURGE {slug}\n".encode()


def purge(slug: str, path: str = SOCKET_PATH) -> str:
    """Ask cdn-edged to purge ``slug`` and return its answer (``ok`` when it did)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(path)
        sock.sendall(purge_request(slug))
        return sock.recv(64).decode("utf-8").strip()
