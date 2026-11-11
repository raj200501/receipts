"""unitconv: unit conversion for the shipping desk."""

from unitconv.aliases import normalize_unit
from unitconv.conversions import (
    UNITS,
    Unit,
    convert,
    dimension_of,
    register_unit,
    units_by_dimension,
)
from unitconv.errors import DimensionMismatchError, UnitError, UnknownUnitError
from unitconv.quantity import format_number, format_quantity, parse_quantity

__version__ = "1.7.0"

__all__ = [
    "UNITS",
    "DimensionMismatchError",
    "Unit",
    "UnitError",
    "UnknownUnitError",
    "convert",
    "dimension_of",
    "format_number",
    "format_quantity",
    "normalize_unit",
    "parse_quantity",
    "register_unit",
    "units_by_dimension",
]
