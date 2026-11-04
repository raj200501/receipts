"""Exceptions raised by tariffs."""

from __future__ import annotations


class TariffError(Exception):
    """Base class of the errors that tariffs raises for bad rate data or unknown places."""


class UnknownZoneError(TariffError, LookupError):
    """A country or zone code that the rate card does not know.

    Attributes:
        code: The code that was looked up.
    """

    def __init__(self, code: str, kind: str = "zone") -> None:
        self.code = code
        super().__init__(f"unknown {kind} {code!r}")


class RateFileError(TariffError, ValueError):
    """A rate file that cannot be read or does not have the expected shape."""
