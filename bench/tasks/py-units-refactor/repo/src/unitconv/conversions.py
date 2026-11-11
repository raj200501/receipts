"""Conversions between units of the same dimension.

Every value is converted through the base unit of its dimension: the metre for length,
the kilogram for mass, the litre for volume, and degrees Celsius for temperature.
``to_base`` turns a value in some unit into the base unit, ``from_base`` turns a value
in the base unit into some unit, and ``convert`` chains the two.

When you add a unit, add it to ``dimension_of``, ``to_base``, and ``from_base``.
"""

from __future__ import annotations

from unitconv.errors import DimensionMismatchError, UnitError, UnknownUnitError

#: Absolute zero in degrees Celsius, the base unit of temperature.
ABSOLUTE_ZERO_C = -273.15

LENGTH_UNITS = ("mm", "cm", "m", "km", "in", "ft", "yd", "mi", "nmi")
MASS_UNITS = ("g", "kg", "t", "oz", "lb", "st")
VOLUME_UNITS = ("ml", "l", "m3", "floz", "pt", "qt", "gal")
TEMPERATURE_UNITS = ("C", "F", "K")


def dimension_of(unit: str) -> str:
    """The dimension of ``unit``: ``length``, ``mass``, ``volume``, or ``temperature``.

    Raises:
        UnknownUnitError: ``unit`` is not a unit symbol that unitconv knows.
    """
    if unit in LENGTH_UNITS:
        return "length"
    if unit in MASS_UNITS:
        return "mass"
    if unit in VOLUME_UNITS:
        return "volume"
    if unit in TEMPERATURE_UNITS:
        return "temperature"
    raise UnknownUnitError(unit)


def to_base(value: float, unit: str) -> float:
    """``value``, given in ``unit``, in the base unit of the unit's dimension.

    Raises:
        UnknownUnitError: there is no conversion from ``unit``.
    """
    # Length, in metres.
    if unit == "mm":
        return value / 1000
    elif unit == "cm":
        return value / 100
    elif unit == "m":
        return value
    elif unit == "km":
        return value * 1000
    elif unit == "in":
        return value * 0.0254
    elif unit == "ft":
        return value * 0.3048
    elif unit == "yd":
        return value * 0.9144
    elif unit == "mi":
        return value * 1609.344
    elif unit == "nmi":
        return value * 1852
    # Mass, in kilograms.
    elif unit == "g":
        return value / 1000
    elif unit == "kg":
        return value
    elif unit == "t":
        return value * 1000
    elif unit == "oz":
        return value * 0.028349523125
    elif unit == "lb":
        return value * 0.45359237
    elif unit == "st":
        return value * 6.35029318
    # Volume, in litres (US customary units).
    elif unit == "ml":
        return value / 1000
    elif unit == "l":
        return value
    elif unit == "m3":
        return value * 1000
    elif unit == "floz":
        return value * 0.0295735295625
    elif unit == "pt":
        return value * 0.473176473
    elif unit == "qt":
        return value * 0.946352946
    elif unit == "gal":
        return value * 3.785411784
    # Temperature, in degrees Celsius.
    elif unit == "C":
        return value
    elif unit == "F":
        return (value - 32) * 5 / 9
    elif unit == "K":
        return value - 273.15
    else:
        raise UnknownUnitError(unit)


def from_base(value: float, unit: str) -> float:
    """``value``, given in the base unit of ``unit``'s dimension, in ``unit``.

    Raises:
        UnknownUnitError: there is no conversion to ``unit``.
    """
    # Length, from metres.
    if unit == "mm":
        return value * 1000
    elif unit == "cm":
        return value * 100
    elif unit == "m":
        return value
    elif unit == "km":
        return value / 1000
    elif unit == "in":
        return value / 0.0254
    elif unit == "ft":
        return value / 0.3048
    elif unit == "yd":
        return value / 0.9144
    elif unit == "mi":
        return value / 1609.344
    # Mass, from kilograms.
    elif unit == "g":
        return value * 1000
    elif unit == "kg":
        return value
    elif unit == "t":
        return value / 1000
    elif unit == "oz":
        return value / 0.028349523125
    elif unit == "lb":
        return value / 0.45359237
    # Volume, from litres.
    elif unit == "ml":
        return value * 1000
    elif unit == "l":
        return value
    elif unit == "m3":
        return value / 1000
    elif unit == "floz":
        return value / 0.0295735295625
    elif unit == "pt":
        return value / 0.473176473
    elif unit == "qt":
        return value / 0.946352946
    elif unit == "gal":
        return value / 3.785411784
    # Temperature, from degrees Celsius.
    elif unit == "C":
        return value
    elif unit == "F":
        return value * 9 / 5 + 32
    elif unit == "K":
        return value + 273.15
    else:
        raise UnknownUnitError(unit)


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` from the unit ``source`` to the unit ``target``.

    Both units are symbols such as ``ft`` or ``kg``; the command line maps names such as
    ``feet`` to symbols first (see :mod:`unitconv.aliases`).

    Raises:
        UnknownUnitError: either unit is not known.
        DimensionMismatchError: the units measure different dimensions.
        UnitError: the value is a temperature below absolute zero.
    """
    source_dimension = dimension_of(source)
    target_dimension = dimension_of(target)
    if source_dimension != target_dimension:
        raise DimensionMismatchError(source, source_dimension, target, target_dimension)
    base = to_base(float(value), source)
    if source_dimension == "temperature" and base < ABSOLUTE_ZERO_C:
        raise UnitError(f"{value:g} {source} is below absolute zero")
    if source == target:
        return float(value)
    return from_base(base, target)
