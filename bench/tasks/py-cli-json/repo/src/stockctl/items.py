"""Reading stock items from the CSV export of the warehouse system."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

COLUMNS = ("sku", "name", "qty", "unit_price", "location", "reorder_at", "updated")
CENT = Decimal("0.01")


class ItemError(ValueError):
    """A row of the export cannot be read; ``line`` is its 1-based line number."""

    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason


@dataclass(frozen=True)
class Item:
    """One stock item."""

    sku: str
    name: str
    qty: int
    unit_price: Decimal
    location: str
    reorder_at: int | None
    updated: date

    def is_low(self) -> bool:
        """True when the quantity is at or below the reorder level."""
        return self.reorder_at is not None and self.qty <= self.reorder_at

    def short_by(self) -> int:
        """How many units are missing to reach the reorder level (0 when not low)."""
        if self.reorder_at is None or not self.is_low():
            return 0
        return self.reorder_at - self.qty

    def value(self) -> Decimal:
        """Stock value of this item."""
        return (self.unit_price * self.qty).quantize(CENT)


def _whole_number(field: str, raw: str, line: int) -> int:
    try:
        number = int(raw.strip())
    except ValueError:
        raise ItemError(line, f"{field} must be a whole number, got {raw!r}") from None
    if number < 0:
        raise ItemError(line, f"{field} must not be negative, got {raw!r}")
    return number


def _amount(raw: str, line: int) -> Decimal:
    try:
        amount = Decimal(raw.strip())
    except InvalidOperation:
        raise ItemError(line, f"unit_price must be an amount, got {raw!r}") from None
    if not amount.is_finite() or amount < 0:
        raise ItemError(line, f"unit_price must be an amount, got {raw!r}")
    if amount != amount.quantize(CENT):
        raise ItemError(line, f"unit_price has more than two decimals: {raw!r}")
    return amount.quantize(CENT)


def _parse_row(row: list[str], line: int) -> Item:
    if len(row) != len(COLUMNS):
        raise ItemError(line, f"expected {len(COLUMNS)} fields, found {len(row)}")
    sku, name, qty, price, location, reorder, updated = (field.strip() for field in row)
    if not sku:
        raise ItemError(line, "sku is empty")
    if not location:
        raise ItemError(line, "location is empty")
    try:
        day = date.fromisoformat(updated)
    except ValueError:
        raise ItemError(line, f"updated must be an ISO date, got {updated!r}") from None
    return Item(
        sku=sku,
        name=name,
        qty=_whole_number("qty", qty, line),
        unit_price=_amount(price, line),
        location=location,
        reorder_at=_whole_number("reorder_at", reorder, line) if reorder else None,
        updated=day,
    )


def parse_items(text: str) -> list[Item]:
    """Parse the text of an export; raises :class:`ItemError` naming the bad line."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        raise ItemError(1, "the file is empty")
    if tuple(field.strip() for field in header) != COLUMNS:
        raise ItemError(1, "expected the header " + ",".join(COLUMNS))
    items: list[Item] = []
    first_line: dict[str, int] = {}
    for row in reader:
        if not row:
            continue
        line = reader.line_num
        item = _parse_row(row, line)
        if item.sku in first_line:
            raise ItemError(
                line, f"duplicate sku {item.sku} (first on line {first_line[item.sku]})"
            )
        first_line[item.sku] = line
        items.append(item)
    return items


def read_items(path: str | Path) -> list[Item]:
    """Read and parse the export at ``path``."""
    return parse_items(Path(path).read_text(encoding="utf-8"))
