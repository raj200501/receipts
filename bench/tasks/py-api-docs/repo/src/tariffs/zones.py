"""Which rate zone a destination country belongs to."""

from __future__ import annotations

from tariffs.errors import UnknownZoneError

#: ISO 3166 alpha-2 country code -> zone code of the rate card.
COUNTRY_ZONES: dict[str, str] = {
    "DE": "EU1",
    "FR": "EU1",
    "NL": "EU1",
    "BE": "EU1",
    "AT": "EU1",
    "ES": "EU2",
    "IT": "EU2",
    "PT": "EU2",
    "PL": "EU3",
    "CZ": "EU3",
    "HU": "EU3",
    "GB": "UK",
    "US": "US",
    "CA": "US",
    "JP": "WORLD",
    "AU": "WORLD",
    "BR": "WORLD",
}


def zone_for(country: str) -> str:
    """The zone code for a two-letter country code (any case).

    Raises:
        UnknownZoneError: the rate card has no zone for ``country``.
    """
    code = country.strip().upper()
    try:
        return COUNTRY_ZONES[code]
    except KeyError:
        raise UnknownZoneError(country, kind="country") from None
