"""Post due dates to the support ticket queue.

The queue's API needs the token in the ``TICKETS_API_TOKEN`` environment variable. The
CI runner provides it; developer machines usually do not.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date

API_URL = "https://tickets.office.internal/api/due-dates"
TOKEN_VARIABLE = "TICKETS_API_TOKEN"


def due_date_payload(ticket: str, opened: date, business_days: int, due: date) -> dict[str, object]:
    """The JSON document the ticket queue accepts for one due date."""
    return {
        "ticket": ticket,
        "opened": opened.isoformat(),
        "business_days": business_days,
        "due": due.isoformat(),
    }


def post_due_date(payload: dict[str, object], timeout_s: float = 5.0) -> int:
    """Send one due date to the ticket queue and return the HTTP status."""
    token = os.environ[TOKEN_VARIABLE]
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return int(response.status)
