"""Push snapshots of a store to the operations backup server.

Every night each kiosk pushes a snapshot of its store to the backup server at
``backup.ops.internal``, which is reachable only from the operations network.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request

from kvstore.store import Store

BACKUP_URL = "https://backup.ops.internal/kvstore/snapshots"


def snapshot(store: Store, host: str) -> dict[str, object]:
    """The snapshot document of one kiosk: its entries and a checksum of them."""
    entries = dict(store.items())
    body = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return {
        "host": host,
        "entries": entries,
        "count": len(entries),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def push(document: dict[str, object], url: str = BACKUP_URL, timeout_s: float = 10.0) -> int:
    """Send one snapshot to the backup server and return the HTTP status."""
    request = urllib.request.Request(
        f"{url}/{document['host']}",
        data=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return int(response.status)
