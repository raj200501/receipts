"""Totals over a list of items."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from stockctl.items import CENT, Item


@dataclass(frozen=True)
class Summary:
    """Totals for a stock list."""

    items: int
    units: int
    low: int
    value: Decimal
    by_location: dict[str, int] = field(default_factory=dict)


def summarize(items: Iterable[Item]) -> Summary:
    """Count items and units, the low items, the stock value, and units per location."""
    rows = list(items)
    per_location: dict[str, int] = {}
    for item in rows:
        per_location[item.location] = per_location.get(item.location, 0) + item.qty
    return Summary(
        items=len(rows),
        units=sum(item.qty for item in rows),
        low=sum(1 for item in rows if item.is_low()),
        value=sum((item.value() for item in rows), Decimal(0)).quantize(CENT),
        by_location=dict(sorted(per_location.items())),
    )
