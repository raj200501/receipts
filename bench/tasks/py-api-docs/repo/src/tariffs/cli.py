"""Command line interface: ``python -m tariffs quote|zones``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tariffs.errors import TariffError
from tariffs.money import format_money
from tariffs.quote import quote
from tariffs.rates import load_rates
from tariffs.zones import zone_for

DEFAULT_RATES = "data/rates.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tariffs", description="Parcel shipping quotes.")
    commands = parser.add_subparsers(dest="command", required=True)
    price = commands.add_parser("quote", help="print the price of a parcel")
    price.add_argument("--country", required=True, help="destination, two-letter code")
    price.add_argument("--weight", required=True, type=float, help="weight in kilograms")
    price.add_argument("--rates", default=DEFAULT_RATES, help="rate file")
    zones = commands.add_parser("zones", help="list the zones of the rate card")
    zones.add_argument("--rates", default=DEFAULT_RATES, help="rate file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool; returns 0 on success and 2 for bad input or an unreadable rate file."""
    parser = _build_parser()
    try:
        options = parser.parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code else 0
    try:
        table = load_rates(options.rates)
        if options.command == "zones":
            for zone in table.zones:
                line = table.rate(zone)
                base = format_money(line.base_cents, table.currency)
                per_kg = format_money(line.per_kg_cents, table.currency)
                print(f"{zone}: {base} + {per_kg}/kg, up to {line.max_kg} kg")
            return 0
        cents = quote(table, zone_for(options.country), options.weight)
        print(format_money(cents, table.currency))
    except (TariffError, ValueError) as err:
        print(f"tariffs: error: {err}", file=sys.stderr)
        return 2
    return 0
