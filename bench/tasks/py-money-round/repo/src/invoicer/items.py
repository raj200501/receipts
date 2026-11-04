"""Read invoice lines from the order system's CSV export."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from invoicer.money import parse_number, round_cents

HEADER = ("invoice", "customer", "description", "quantity", "unit_price", "vat_rate")


class ItemError(ValueError):
    """A row of the export that cannot be read as an invoice line."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass(frozen=True)
class LineItem:
    """One line of an invoice, as exported by the order system.

    ``vat_rate`` is a percentage (``20`` means 20 percent); ``line`` is the line of the
    export the item was read from, used in error messages.
    """

    invoice: str
    customer: str
    description: str
    quantity: float
    unit_price: float
    vat_rate: float
    line: int = 0

    @property
    def amount(self) -> float:
        """The line amount: quantity times unit price, rounded to the cent."""
        return round_cents(self.quantity * self.unit_price)


def _number(text: str, what: str, line: int) -> float:
    try:
        return parse_number(text)
    except ValueError:
        raise ItemError(line, f"invalid {what} {text.strip()!r}") from None


def parse_row(row: list[str], line: int) -> LineItem:
    """Turn one CSV row into a :class:`LineItem`; ``line`` is used in error messages."""
    if len(row) != len(HEADER):
        raise ItemError(line, f"expected {len(HEADER)} fields, got {len(row)}")
    invoice, customer, description = (field.strip() for field in row[:3])
    if not invoice:
        raise ItemError(line, "missing invoice number")
    if not description:
        raise ItemError(line, "missing description")
    quantity = _number(row[3], "quantity", line)
    unit_price = _number(row[4], "unit price", line)
    vat_rate = _number(row[5], "VAT rate", line)
    if not 0 <= vat_rate <= 100:
        raise ItemError(line, f"VAT rate must be from 0 to 100, got {row[5].strip()}")
    return LineItem(invoice, customer, description, quantity, unit_price, vat_rate, line)


def parse_items(text: str) -> list[LineItem]:
    """Parse export text that starts with the header row; blank lines are skipped."""
    reader = csv.reader(io.StringIO(text))
    items: list[LineItem] = []
    seen_header = False
    for row in reader:
        if not any(field.strip() for field in row):
            continue
        if not seen_header:
            if tuple(field.strip() for field in row) != HEADER:
                raise ItemError(reader.line_num, f"expected the header {','.join(HEADER)}")
            seen_header = True
            continue
        items.append(parse_row(row, reader.line_num))
    return items


def read_items(path: Path) -> list[LineItem]:
    """Read the invoice lines of an export file."""
    return parse_items(path.read_text(encoding="utf-8"))
