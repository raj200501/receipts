"""Client for the partner order-status API.

The API needs a bearer token that only the CI runner has (``PARTNER_API_TOKEN``); this
module builds the request and reads the token from the environment.
"""

from __future__ import annotations

import json
import os
import urllib.request

BASE_URL = "https://orders.partner.example.invalid/v1"


def token() -> str:
    """The API token from the environment."""
    value = os.environ.get("PARTNER_API_TOKEN", "")
    if not value:
        raise RuntimeError("PARTNER_API_TOKEN is not set")
    return value


def build_request(order_id: str, api_token: str) -> urllib.request.Request:
    """The GET request for one order."""
    return urllib.request.Request(
        f"{BASE_URL}/orders/{order_id}",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )


def order_status(order_id: str, timeout_s: float = 5.0) -> str:
    """The status string of an order, as the partner API reports it."""
    with urllib.request.urlopen(build_request(order_id, token()), timeout=timeout_s) as reply:
        return str(json.load(reply)["status"])
