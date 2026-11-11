"""JSON output for the stockctl commands, encoded as docs/JSON_CONTRACT.md says."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from stockctl.items import Item, ItemError
from stockctl.stats import Summary


def item_to_dict(item: Item, *, with_short_by: bool = False) -> dict[str, Any]:
    """One item as a JSON-ready dict: counts as integers, money as two-decimal strings."""
    data: dict[str, Any] = {
        "sku": item.sku,
        "name": item.name,
        "qty": item.qty,
        "unit_price": f"{item.unit_price:.2f}",
        "location": item.location,
        "reorder_at": item.reorder_at,
        "updated": item.updated.isoformat(),
    }
    if with_short_by:
        data["short_by"] = item.short_by()
    return data


def summary_to_dict(summary: Summary) -> dict[str, Any]:
    """The summary as a JSON-ready dict."""
    return {
        "items": summary.items,
        "units": summary.units,
        "low": summary.low,
        "value": f"{summary.value:.2f}",
        "locations": dict(summary.by_location),
    }


def format_items(items: Sequence[Item], *, with_short_by: bool = False) -> str:
    """A JSON array with one object per item."""
    return json.dumps([item_to_dict(item, with_short_by=with_short_by) for item in items], indent=2)


def format_summary(summary: Summary) -> str:
    """The summary as a JSON object."""
    return json.dumps(summary_to_dict(summary), indent=2)


def format_error(message: str, line: int | None = None) -> str:
    """A one-line JSON object describing a failure."""
    return json.dumps({"error": message, "line": line})


def format_item_error(exc: ItemError) -> str:
    """A one-line JSON object for a row that cannot be read."""
    return format_error(exc.reason, exc.line)
