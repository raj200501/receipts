"""Per-column statistics: filled and distinct counts, and the range and mean of numbers."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from csvsummary.reader import Table

_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class ColumnStats:
    """What the summary reports about one column.

    ``minimum`` and ``maximum`` keep the text of the file. They and ``mean`` are only
    set when the column has filled values and every one of them is a number.
    """

    name: str
    filled: int
    distinct: int
    minimum: str = ""
    maximum: str = ""
    mean: Decimal | None = None

    @property
    def numeric(self) -> bool:
        """True when every filled value of the column is a number."""
        return self.mean is not None


def as_number(text: str) -> Decimal | None:
    """``text`` as a number (optional sign, digits, optional decimal part), else None.

    Thousands separators and exponents are not numbers here: exports write plain
    decimals, and a value such as ``1,250`` is more often a typo than a number.
    """
    value = text.strip()
    if not _NUMBER.fullmatch(value):
        return None
    return Decimal(value)


def filled_values(values: Sequence[str]) -> list[str]:
    """The values that are not empty, without surrounding whitespace."""
    return [value.strip() for value in values if value.strip()]


def column_stats(name: str, values: Sequence[str]) -> ColumnStats:
    """Statistics of one column from its values in row order."""
    filled = filled_values(values)
    distinct = len(set(filled))
    numbers = [as_number(value) for value in filled]
    if not filled or any(number is None for number in numbers):
        return ColumnStats(name, len(filled), distinct)
    pairs = sorted(zip(numbers, filled, strict=True), key=lambda pair: pair[0])
    total = sum(number for number, _ in pairs)
    mean = total / len(pairs)
    return ColumnStats(name, len(filled), distinct, pairs[0][1], pairs[-1][1], mean)


def summarize(table: Table) -> list[ColumnStats]:
    """Statistics of every column, in header order."""
    return [column_stats(name, table.column(name)) for name in table.header]


def top_values(values: Sequence[str], limit: int = 10) -> list[tuple[str, int]]:
    """The most common values with their counts: most common first, then by value.

    Values are compared without surrounding whitespace. Empty values are counted
    too, as the empty string.
    """
    counts = Counter(value.strip() for value in values)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]
