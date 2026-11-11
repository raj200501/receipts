"""Selecting and ordering items."""

from __future__ import annotations

from collections.abc import Iterable

from stockctl.items import Item

SORT_KEYS = ("sku", "name", "qty")


def by_location(items: Iterable[Item], location: str | None) -> list[Item]:
    """Items stored at ``location`` (all items when it is None)."""
    if location is None:
        return list(items)
    return [item for item in items if item.location == location]


def low_items(items: Iterable[Item]) -> list[Item]:
    """Items at or below their reorder level, the most short first."""
    low = [item for item in items if item.is_low()]
    return sorted(low, key=lambda item: (-item.short_by(), item.sku))


def sort_items(items: Iterable[Item], key: str = "sku") -> list[Item]:
    """Items ordered by ``key``: sku, name (case-insensitive), or qty (largest first)."""
    if key == "sku":
        return sorted(items, key=lambda item: item.sku)
    if key == "name":
        return sorted(items, key=lambda item: (item.name.lower(), item.sku))
    if key == "qty":
        return sorted(items, key=lambda item: (-item.qty, item.sku))
    raise ValueError(f"unknown sort key {key!r}; use one of {', '.join(SORT_KEYS)}")
