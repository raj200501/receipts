"""Money amounts: parsing numbers from the export, rounding to the cent, and formatting.

Invoice amounts are euros with two decimal places; docs/ROUNDING.md is finance's policy
for how they are rounded.
"""

from __future__ import annotations

CENT_DIGITS = 2


def parse_number(text: str) -> float:
    """Parse a quantity, unit price, or VAT rate such as ``12.50``, ``-3``, or ``5.5``.

    Surrounding spaces are ignored.

    Raises:
        ValueError: ``text`` is empty or is not a number.
    """
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("empty number")
    return float(cleaned)


def round_cents(value: float) -> float:
    """Round ``value`` to the cent."""
    return round(value, CENT_DIGITS)


def format_amount(value: float) -> str:
    """Format an amount with two decimal places, such as ``1234.50`` or ``-0.75``."""
    return f"{value:.{CENT_DIGITS}f}"


def format_rate(rate: float) -> str:
    """Format a VAT rate without trailing zeros: ``20``, ``7``, ``5.5``."""
    return f"{rate:g}"
