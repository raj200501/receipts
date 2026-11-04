"""Formatting of amounts of money, which tariffs keeps in whole cents."""

from __future__ import annotations


def format_money(cents: int, currency: str = "EUR") -> str:
    """Format an amount in cents as ``12.34 EUR``.

    Args:
        cents: The amount in cents; not negative.
        currency: The currency code to print after the amount.

    Raises:
        ValueError: ``cents`` is negative.
        TypeError: ``cents`` is not an integer.
    """
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError(f"cents must be an integer, not {type(cents).__name__}")
    if cents < 0:
        raise ValueError(f"cents must not be negative, got {cents}")
    whole, fraction = divmod(cents, 100)
    return f"{whole}.{fraction:02d} {currency}"
