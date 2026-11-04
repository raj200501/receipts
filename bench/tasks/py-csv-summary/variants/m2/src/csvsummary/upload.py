"""Upload column profiles of an export to the analytics data catalog.

The data catalog shows, for every dataset the reporting jobs load, how many rows the
last export had and which of its columns are filled and numeric. Its API is reachable
only from the office network; this module builds the profile document and sends it.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Sequence
from typing import Any

from csvsummary.stats import ColumnStats

CATALOG_URL = "https://catalog.analytics.internal/api/v2/datasets"


def profile(dataset: str, rows: int, columns: Sequence[ColumnStats]) -> dict[str, Any]:
    """The JSON document the data catalog accepts for one dataset."""
    return {
        "dataset": dataset,
        "rows": rows,
        "columns": [
            {"name": c.name, "filled": c.filled, "distinct": c.distinct, "numeric": c.numeric}
            for c in columns
        ],
    }


def upload(document: dict[str, Any], timeout_s: float = 5.0) -> int:
    """Send one profile to the data catalog and return the HTTP status."""
    request = urllib.request.Request(
        f"{CATALOG_URL}/{document['dataset']}/profile",
        data=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return int(response.status)
