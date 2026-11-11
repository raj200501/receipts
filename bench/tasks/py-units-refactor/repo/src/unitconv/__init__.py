"""unitconv: unit conversion for the shipping desk."""

from unitconv.aliases import normalize_unit
from unitconv.conversions import convert, dimension_of
from unitconv.errors import DimensionMismatchError, UnitError, UnknownUnitError
from unitconv.quantity import format_number, format_quantity, parse_quantity

__version__ = "1.6.0"

__all__ = [
    "DimensionMismatchError",
    "UnitError",
    "UnknownUnitError",
    "convert",
    "dimension_of",
    "format_number",
    "format_quantity",
    "normalize_unit",
    "parse_quantity",
]
