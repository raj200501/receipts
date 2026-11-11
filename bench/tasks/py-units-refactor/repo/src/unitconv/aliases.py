"""Unit names that people type, and the unit symbols they stand for.

The library works with symbols only (``ft``, ``kg``, ``C``). The command line accepts
names as well, so ``unitconv convert 3 feet metres`` works; :func:`normalize_unit` maps
a name to its symbol.
"""

from __future__ import annotations

ALIASES: dict[str, str] = {
    # length
    "millimetre": "mm",
    "millimetres": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "centimetre": "cm",
    "centimetres": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    "kilometre": "km",
    "kilometres": "km",
    "kilometer": "km",
    "kilometers": "km",
    "inch": "in",
    "inches": "in",
    "foot": "ft",
    "feet": "ft",
    "yard": "yd",
    "yards": "yd",
    "mile": "mi",
    "miles": "mi",
    "nautical mile": "nmi",
    "nautical miles": "nmi",
    # mass
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "tonne": "t",
    "tonnes": "t",
    "ounce": "oz",
    "ounces": "oz",
    "pound": "lb",
    "pounds": "lb",
    "lbs": "lb",
    "stone": "st",
    # volume
    "millilitre": "ml",
    "millilitres": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "L": "l",
    "cubic metre": "m3",
    "cubic metres": "m3",
    "cubic meter": "m3",
    "cubic meters": "m3",
    "fluid ounce": "floz",
    "fluid ounces": "floz",
    "fl oz": "floz",
    "pint": "pt",
    "pints": "pt",
    "quart": "qt",
    "quarts": "qt",
    "gallon": "gal",
    "gallons": "gal",
    # temperature
    "celsius": "C",
    "degC": "C",
    "\N{DEGREE SIGN}C": "C",
    "fahrenheit": "F",
    "degF": "F",
    "\N{DEGREE SIGN}F": "F",
    "kelvin": "K",
}


def normalize_unit(name: str) -> str:
    """The unit symbol for ``name``.

    A name in :data:`ALIASES` (matched exactly, then in lower case, with runs of spaces
    treated as one space) gives its symbol. Anything else, including every symbol, comes
    back with its surrounding spaces removed, so that an unknown name is reported as an
    unknown unit by the conversion.
    """
    text = " ".join(name.split())
    if text in ALIASES:
        return ALIASES[text]
    return ALIASES.get(text.lower(), text)
