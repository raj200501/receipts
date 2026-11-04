"""Plain-text output for the stockctl commands."""

from __future__ import annotations

from collections.abc import Sequence

from stockctl.items import Item
from stockctl.stats import Summary


def format_list(items: Sequence[Item]) -> str:
    """A table with one line per item."""
    if not items:
        return "(no items)\n"
    sku_w = max(len("SKU"), *(len(item.sku) for item in items))
    name_w = max(len("NAME"), *(len(item.name) for item in items))
    qty_w = max(len("QTY"), *(len(str(item.qty)) for item in items))
    lines = [f"{'SKU':<{sku_w}}  {'NAME':<{name_w}}  {'QTY':>{qty_w}}  LOCATION"]
    for item in items:
        lines.append(
            f"{item.sku:<{sku_w}}  {item.name:<{name_w}}  {item.qty:>{qty_w}}  {item.location}"
        )
    return "\n".join(lines) + "\n"


def format_low(items: Sequence[Item]) -> str:
    """One line per low item, saying how far below the reorder level it is."""
    if not items:
        return "nothing to reorder\n"
    lines = [
        f"{item.sku}  {item.name}: {item.qty} left, reorder at {item.reorder_at}, "
        f"short by {item.short_by()}"
        for item in items
    ]
    return "\n".join(lines) + "\n"


def format_summary(summary: Summary) -> str:
    """The summary block."""
    lines = [
        f"items: {summary.items}",
        f"units: {summary.units}",
        f"low: {summary.low}",
        f"value: {summary.value}",
    ]
    lines.extend(f"  {name}: {units}" for name, units in summary.by_location.items())
    return "\n".join(lines) + "\n"
