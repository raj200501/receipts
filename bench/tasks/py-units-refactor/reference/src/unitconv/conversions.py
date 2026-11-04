"""Conversions between units of the same dimension, driven by one table.

Every unit has one entry in :data:`UNITS`: its dimension, its factor to the base unit of
that dimension, and an offset (only the temperature scales have one). A value ``v`` in a
unit is ``v * factor + offset`` in the base unit: the metre for length, the kilogram for
mass, the litre for volume, and degrees Celsius for temperature. ``to_base``,
``from_base``, ``dimension_of``, and ``convert`` all read the table, so a unit works in
both directions as soon as it has an entry. Add built-in units to the table below, and
units that only one program needs with :func:`register_unit` at run time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from unitconv.errors import DimensionMismatchError, UnitError, UnknownUnitError

#: Absolute zero in degrees Celsius, the base unit of temperature.
ABSOLUTE_ZERO_C = -273.15

#: The base unit of each dimension.
BASE_UNITS: dict[str, str] = {"length": "m", "mass": "kg", "volume": "l", "temperature": "C"}


@dataclass(frozen=True)
class Unit:
    """One entry of the conversion table.

    Attributes:
        symbol: The unit symbol, such as ``ft``.
        dimension: ``length``, ``mass``, ``volume``, ``temperature``, or a dimension
            added with :func:`register_unit`.
        factor: A value in this unit times ``factor`` (plus ``offset``) is the value
            in the base unit of the dimension.
        offset: Added after the factor; zero except for temperature scales.
    """

    symbol: str
    dimension: str
    factor: float
    offset: float = 0.0

    def to_base(self, value: float) -> float:
        """``value`` in this unit, in the base unit of the dimension."""
        return value * self.factor + self.offset

    def from_base(self, value: float) -> float:
        """``value`` in the base unit of the dimension, in this unit."""
        return (value - self.offset) / self.factor


def _table(*units: Unit) -> dict[str, Unit]:
    return {unit.symbol: unit for unit in units}


#: The conversion table: unit symbol to its entry, grouped by dimension.
UNITS: dict[str, Unit] = _table(
    # Length, in metres.
    Unit("mm", "length", 0.001),
    Unit("cm", "length", 0.01),
    Unit("m", "length", 1.0),
    Unit("km", "length", 1000.0),
    Unit("in", "length", 0.0254),
    Unit("ft", "length", 0.3048),
    Unit("yd", "length", 0.9144),
    Unit("mi", "length", 1609.344),
    Unit("nmi", "length", 1852.0),
    # Mass, in kilograms.
    Unit("g", "mass", 0.001),
    Unit("kg", "mass", 1.0),
    Unit("t", "mass", 1000.0),
    Unit("oz", "mass", 0.028349523125),
    Unit("lb", "mass", 0.45359237),
    Unit("st", "mass", 6.35029318),
    # Volume, in litres (US customary units).
    Unit("ml", "volume", 0.001),
    Unit("l", "volume", 1.0),
    Unit("m3", "volume", 1000.0),
    Unit("floz", "volume", 0.0295735295625),
    Unit("pt", "volume", 0.473176473),
    Unit("qt", "volume", 0.946352946),
    Unit("gal", "volume", 3.785411784),
    # Temperature, in degrees Celsius: F is (value - 32) * 5 / 9, K is value - 273.15.
    Unit("C", "temperature", 1.0),
    Unit("F", "temperature", 5 / 9, -160 / 9),
    Unit("K", "temperature", 1.0, -273.15),
)


def lookup(unit: str) -> Unit:
    """The table entry of the unit symbol ``unit``.

    Raises:
        UnknownUnitError: ``unit`` is not in the table.
    """
    try:
        return UNITS[unit]
    except KeyError:
        raise UnknownUnitError(unit) from None


def register_unit(symbol: str, dimension: str, factor: float, offset: float = 0.0) -> Unit:
    """Add a unit to the conversion table and return its entry.

    A value ``v`` in the new unit is ``v * factor + offset`` in the base unit of
    ``dimension``; the unit then converts to and from every unit of that dimension.

    Raises:
        ValueError: ``symbol`` is already in the table (the table is left as it was),
            the symbol or the dimension is empty, or ``factor`` is zero or not finite.
    """
    if symbol in UNITS:
        raise ValueError(f"unit {symbol!r} is already in the conversion table")
    if not symbol.strip() or not dimension.strip():
        raise ValueError("a unit needs a symbol and a dimension")
    if factor == 0 or not math.isfinite(factor) or not math.isfinite(offset):
        raise ValueError(f"unit {symbol!r} needs a finite, non-zero factor")
    unit = Unit(symbol, dimension, float(factor), float(offset))
    UNITS[symbol] = unit
    return unit


def units_by_dimension() -> dict[str, list[str]]:
    """The unit symbols of each dimension, in table order."""
    groups: dict[str, list[str]] = {}
    for unit in UNITS.values():
        groups.setdefault(unit.dimension, []).append(unit.symbol)
    return groups


def dimension_of(unit: str) -> str:
    """The dimension of ``unit``: ``length``, ``mass``, ``volume``, or ``temperature``.

    Raises:
        UnknownUnitError: ``unit`` is not a unit symbol that unitconv knows.
    """
    return lookup(unit).dimension


def to_base(value: float, unit: str) -> float:
    """``value``, given in ``unit``, in the base unit of the unit's dimension.

    Raises:
        UnknownUnitError: ``unit`` is not in the table.
    """
    return lookup(unit).to_base(value)


def from_base(value: float, unit: str) -> float:
    """``value``, given in the base unit of ``unit``'s dimension, in ``unit``.

    Raises:
        UnknownUnitError: ``unit`` is not in the table.
    """
    return lookup(unit).from_base(value)


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` from the unit ``source`` to the unit ``target``.

    Both units are symbols such as ``ft`` or ``kg``; the command line maps names such as
    ``feet`` to symbols first (see :mod:`unitconv.aliases`).

    Raises:
        UnknownUnitError: either unit is not known.
        DimensionMismatchError: the units measure different dimensions.
        UnitError: the value is a temperature below absolute zero.
    """
    source_unit = lookup(source)
    target_unit = lookup(target)
    if source_unit.dimension != target_unit.dimension:
        raise DimensionMismatchError(source, source_unit.dimension, target, target_unit.dimension)
    base = source_unit.to_base(float(value))
    if source_unit.dimension == "temperature" and base < ABSOLUTE_ZERO_C:
        raise UnitError(f"{value:g} {source} is below absolute zero")
    if source == target:
        return float(value)
    return target_unit.from_base(base)
