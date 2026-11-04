"""Errors raised by unitconv.

Every error is a :class:`UnitError`, which is a :class:`ValueError`, so callers that
only want to report a bad conversion can catch either.
"""

from __future__ import annotations


class UnitError(ValueError):
    """A value or a unit that cannot be converted."""


class UnknownUnitError(UnitError):
    """A unit symbol that unitconv does not know."""

    def __init__(self, unit: str) -> None:
        super().__init__(f"unknown unit {unit!r}")
        self.unit = unit


class DimensionMismatchError(UnitError):
    """A conversion between units that measure different things (for example m and kg)."""

    def __init__(
        self, source: str, source_dimension: str, target: str, target_dimension: str
    ) -> None:
        super().__init__(
            f"cannot convert {source_dimension} ({source}) to {target_dimension} ({target})"
        )
        self.source = source
        self.target = target
