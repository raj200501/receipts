"""Send a pick list to the warehouse management system (WMS).

The WMS is reachable only from the office network and the warehouse VPN, under
``wms.shop.internal``. Developer laptops and CI runners outside those networks cannot
resolve the name.
"""

from __future__ import annotations

import json
import urllib.request

WMS_URL = "https://wms.shop.internal/api/pick-lists"


def pick_list_payload(order_id: str, picks: list[tuple[str, int]]) -> dict[str, object]:
    """The JSON document the WMS accepts for one order's pick list."""
    return {
        "order": order_id,
        "picks": [{"sku": sku, "qty": qty} for sku, qty in sorted(picks)],
    }


def send_pick_list(payload: dict[str, object], timeout_s: float = 5.0) -> int:
    """Post one pick list to the WMS and return the HTTP status."""
    request = urllib.request.Request(
        WMS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return int(response.status)
