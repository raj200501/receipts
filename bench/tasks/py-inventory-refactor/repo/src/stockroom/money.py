"""Money is whole cents everywhere; percentages round half up."""

from __future__ import annotations


def percent_of(cents: int, pct: int) -> int:
    """``pct`` percent of ``cents``, rounded half up to a whole cent."""
    return (cents * pct + 50) // 100


def format_cents(cents: int) -> str:
    """``1290`` becomes ``12.90``; negative amounts keep their sign."""
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}{whole}.{rest:02d}"
