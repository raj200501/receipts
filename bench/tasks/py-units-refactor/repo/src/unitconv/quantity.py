"""Quantities as text: reading ``12.5 kg`` and writing numbers for people."""

from __future__ import annotations

import math
import re

from unitconv.aliases import normalize_unit
from unitconv.errors import UnitError

_QUANTITY = re.compile(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*([^\d\s].*?)\s*$")


def parse_quantity(text: str) -> tuple[float, str]:
    """Split a quantity such as ``12.5 kg``, ``3.5kg``, or ``12 pounds`` into its value
    and its unit symbol (names are mapped to symbols with :func:`normalize_unit`).

    Raises:
        UnitError: ``text`` is not a number followed by a unit.
    """
    match = _QUANTITY.match(text)
    if match is None:
        raise UnitError(f"expected a number and a unit, got {text.strip()!r}")
    return float(match.group(1)), normalize_unit(match.group(2))


def format_number(value: float, precision: int = 4) -> str:
    """``value`` rounded to ``precision`` decimal places, without trailing zeros.

    ``format_number(3.65760, 4)`` is ``3.6576``, ``format_number(100.0)`` is ``100``,
    and a value that rounds to zero is ``0`` (never ``-0``).
    """
    if precision < 0:
        raise ValueError(f"precision must be 0 or more, got {precision}")
    if not math.isfinite(value):
        raise UnitError(f"not a finite number: {value!r}")
    text = f"{value:.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def format_quantity(value: float, unit: str, precision: int = 4) -> str:
    """``value`` and ``unit`` for output, such as ``3.6576 m``."""
    return f"{format_number(value, precision)} {unit}"
