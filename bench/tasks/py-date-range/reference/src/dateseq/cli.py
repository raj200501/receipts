"""Command line: ``dateseq list START [END]`` and ``dateseq count START [END]``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dateseq.formats import FORMATS, format_dates
from dateseq.periods import PeriodError, parse_step, resolve
from dateseq.ranges import date_range, day_count, weekday_count, weekdays

PERIOD_HELP = "a date (YYYY-MM-DD), a month (YYYY-MM), or an ISO week (YYYY-Www)"


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(prog="dateseq", description="Dates of a period.")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="print every date, one per line")
    counting = commands.add_parser("count", help="print how many dates there are")
    for command in (listing, counting):
        command.add_argument("start", help=f"the first period: {PERIOD_HELP}")
        command.add_argument("end", nargs="?", help="the last period (default: START itself)")
        command.add_argument("--weekdays", action="store_true", help="only Monday to Friday")
    listing.add_argument(
        "--format", choices=sorted(FORMATS), default="iso", help="how to print each date"
    )
    listing.add_argument(
        "--step", default="1", help="every N days (N) or every N weeks (Nw); default 1"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        first, last = resolve(args.start, args.end)
        step = parse_step(args.step) if args.command == "list" else 1
    except PeriodError as exc:
        print(f"dateseq: {exc}", file=sys.stderr)
        return 2
    if args.command == "count":
        print(weekday_count(first, last) if args.weekdays else day_count(first, last))
        return 0
    dates = date_range(first, last, step)
    if args.weekdays:
        dates = weekdays(dates)
    for line in format_dates(dates, args.format):
        print(line)
    return 0
