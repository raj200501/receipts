"""The rate card: one price line per zone, loaded from a JSON file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tariffs.errors import RateFileError, UnknownZoneError


@dataclass(frozen=True)
class ZoneRate:
    """The price line of one zone, in cents.

    Attributes:
        base_cents: Charged for every parcel.
        per_kg_cents: Charged for each started kilogram.
        max_kg: The heaviest parcel the zone accepts.
    """

    base_cents: int
    per_kg_cents: int
    max_kg: int


@dataclass(frozen=True)
class RateTable:
    """All zones of a rate card.

    Attributes:
        currency: The currency code of every amount in the card.
        valid_from: The date the card starts to apply, as ``YYYY-MM-DD`` text.
        by_zone: Zone code -> :class:`ZoneRate`.
    """

    currency: str
    valid_from: str
    by_zone: dict[str, ZoneRate]

    @property
    def zones(self) -> list[str]:
        """The zone codes of the card, sorted."""
        return sorted(self.by_zone)

    def rate(self, zone: str) -> ZoneRate:
        """The price line of ``zone``.

        Raises:
            UnknownZoneError: the card has no such zone.
        """
        try:
            return self.by_zone[zone]
        except KeyError:
            raise UnknownZoneError(zone) from None


def _zone_rate(zone: str, raw: object) -> ZoneRate:
    if not isinstance(raw, dict):
        raise RateFileError(f"zone {zone}: expected an object")
    try:
        values = {key: raw[key] for key in ("base_cents", "per_kg_cents", "max_kg")}
    except KeyError as missing:
        raise RateFileError(f"zone {zone}: missing {missing.args[0]}") from None
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in values.values()):
        raise RateFileError(f"zone {zone}: amounts must be positive whole numbers")
    return ZoneRate(**values)


def load_rates(path: str | Path) -> RateTable:
    """Read a rate file (see the README for its format).

    Raises:
        RateFileError: the file cannot be read, is not JSON, or has the wrong shape.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as err:
        raise RateFileError(f"cannot read rate file {str(path)!r}: {err.strerror}") from err
    except json.JSONDecodeError as err:
        raise RateFileError(f"rate file {str(path)!r} is not valid JSON: {err.msg}") from err
    if not isinstance(document, dict) or not isinstance(document.get("zones"), dict):
        raise RateFileError(f"rate file {str(path)!r} has no 'zones' object")
    currency = document.get("currency", "EUR")
    valid_from = document.get("valid_from", "")
    zones = {name: _zone_rate(name, raw) for name, raw in document["zones"].items()}
    return RateTable(currency=str(currency), valid_from=str(valid_from), by_zone=zones)
