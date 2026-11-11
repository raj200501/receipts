"""Money amounts: parsing numbers from the export, rounding to the cent, and formatting.

Invoice amounts are euros with two decimal places; docs/ROUNDING.md is finance's policy
for how they are rounded. Every number is a :class:`decimal.Decimal`, kept exactly as
written in the export, and rounding goes to the nearest cent with an amount exactly
halfway between two cents going to the even cent (round half to even).
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

CENT = Decimal("0.01")


def parse_number(text: str) -> Decimal:
    """Parse a quantity, unit price, or VAT rate such as ``12.50``, ``-3``, or ``5.5``.

    Surrounding spaces are ignored. The value is exact: ``0.895`` is 0.895, not the
    nearest binary fraction.

    Raises:
        ValueError: ``text`` is empty, is not a number, or is not a finite number
            (``NaN``, ``inf``).
    """
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("empty number")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a number: {cleaned!r}") from None
    if not value.is_finite():
        raise ValueError(f"not a finite number: {cleaned!r}")
    return value


def round_cents(value: Decimal) -> Decimal:
    """Round ``value`` to the cent, halves to the even cent: 2.125 is 2.12, 2.135 is 2.14."""
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def format_amount(value: Decimal) -> str:
    """Format an amount with two decimal places, such as ``1234.50`` or ``-0.75``."""
    return f"{round_cents(value):f}"


def format_rate(rate: Decimal) -> str:
    """Format a VAT rate without trailing zeros: ``20``, ``7``, ``5.5``."""
    return f"{rate.normalize():f}"
