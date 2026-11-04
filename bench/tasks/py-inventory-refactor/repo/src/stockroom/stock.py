"""Stock levels: how many units of each SKU are on the shelf."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class StockError(ValueError):
    """The stock file is missing, unreadable, or not a SKU-to-count mapping."""


@dataclass
class Stock:
    """Units on hand by SKU. Reserving an order takes units off the shelf."""

    on_hand: dict[str, int] = field(default_factory=dict)

    def available(self, sku: str) -> int:
        """Units of ``sku`` on the shelf (0 for a SKU that has no entry)."""
        return self.on_hand.get(sku, 0)

    def take(self, sku: str, qty: int) -> None:
        """Take ``qty`` units off the shelf; the shelf never goes below zero."""
        self.on_hand[sku] = max(0, self.available(sku) - qty)


def load_stock(path: str | Path) -> Stock:
    """Read ``data/stock.json`` (a JSON object from SKU to a whole number of units)."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise StockError(f"cannot read {path}: {exc.strerror or exc}") from None
    except ValueError as exc:
        raise StockError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(document, dict) or not all(
        isinstance(v, int) and v >= 0 for v in document.values()
    ):
        raise StockError(f"{path} must map each SKU to a whole number of units")
    return Stock(on_hand=dict(document))


def save_stock(stock: Stock, path: str | Path) -> None:
    """Write the stock file back, keys sorted, one level of indentation."""
    Path(path).write_text(
        json.dumps(stock.on_hand, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
