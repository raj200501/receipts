"""Ask the mail gateway whether a mailbox exists (used by the nightly import).

``addrcheck`` itself only checks syntax. The import job additionally asks the gateway to
probe the receiving server, which needs the gateway token that only the import hosts and
the CI runner have, in the ``MAILGATE_TOKEN`` environment variable.
"""

from __future__ import annotations

import json
import os
import urllib.request

GATEWAY = "https://mailgate.corp.internal/v1/probe"


def probe_request(address: str, token: str) -> dict[str, object]:
    """The request the gateway expects for ``address``.

    Raises:
        ValueError: ``address`` has no ``@``.
    """
    if "@" not in address:
        raise ValueError(f"not an address: {address!r}")
    return {
        "url": GATEWAY,
        "headers": {"Authorization": f"Bearer {token}"},
        "json": {"address": address},
    }


def probe(address: str) -> str:
    """The gateway's verdict for ``address``: ``exists``, ``unknown``, or ``rejected``.

    Raises:
        RuntimeError: ``MAILGATE_TOKEN`` is not set in the environment.
    """
    token = os.environ.get("MAILGATE_TOKEN")
    if not token:
        raise RuntimeError("MAILGATE_TOKEN is not set; the gateway needs it")
    request = probe_request(address, token)
    http_request = urllib.request.Request(
        GATEWAY,
        data=json.dumps(request["json"]).encode(),
        headers={**request["headers"], "Content-Type": "application/json"},  # type: ignore[dict-item]
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=5) as response:
        return str(json.load(response)["verdict"])
