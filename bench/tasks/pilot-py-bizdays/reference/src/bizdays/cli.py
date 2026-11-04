"""Command line: ``bizdays add``, ``bizdays between``, and ``bizdays check``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from bizdays.arith import add_business_days, business_days_between, is_business_day
from bizdays.calendar import CalendarError, load_all
from bizdays.config import DEFAULT_CONFIG, ConfigError, calendar_sources, project_root


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {text!r} (use YYYY-MM-DD)") from None


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(prog="bizdays", description="Business-day arithmetic.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="configuration file")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="the date COUNT business days after DATE")
    add.add_argument("start", type=_date)
    add.add_argument("count", type=int)
    between = commands.add_parser(
        "between", help="the number of business days after START up to and including END"
    )
    between.add_argument("start", type=_date)
    between.add_argument("end", type=_date)
    check = commands.add_parser("check", help="say whether DATE is a business day")
    check.add_argument("day", type=_date)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        closures = load_all(calendar_sources(args.config), project_root(args.config))
    except (CalendarError, ConfigError) as exc:
        print(f"bizdays: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "add":
            print(add_business_days(args.start, args.count, closures).isoformat())
        elif args.command == "between":
            print(business_days_between(args.start, args.end, closures))
        else:
            business = is_business_day(args.day, closures)
            verdict = "a business day" if business else "not a business day"
            print(f"{args.day.isoformat()} is {verdict}")
    except ValueError as exc:
        print(f"bizdays: {exc}", file=sys.stderr)
        return 2
    return 0
