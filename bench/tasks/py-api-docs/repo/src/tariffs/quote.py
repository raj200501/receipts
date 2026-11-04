"""Price a parcel."""

from __future__ import annotations

import math

from tariffs.rates import RateTable


def quote(table: RateTable, zone: str, weight_kg: float) -> int:
    """The price in cents of a parcel of ``weight_kg`` sent to ``zone``.

    The price is the zone's base charge plus its per-kilogram charge for every started
    kilogram: 2.0 kg is charged as 2 kg, 2.1 kg as 3 kg.

    Raises:
        ValueError: ``weight_kg`` is not positive, or above the zone's limit.
        UnknownZoneError: the table has no such zone.
    """
    line = table.rate(zone)
    if weight_kg <= 0:
        raise ValueError(f"weight must be positive, got {weight_kg}")
    if weight_kg > line.max_kg:
        raise ValueError(f"weight {weight_kg} kg is above the {line.max_kg} kg limit of {zone}")
    return line.base_cents + line.per_kg_cents * math.ceil(weight_kg)
