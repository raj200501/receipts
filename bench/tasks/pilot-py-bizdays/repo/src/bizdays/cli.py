"""Command line: ``bizdays add DATE COUNT`` and ``bizdays check DATE``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from bizdays.arith import add_business_days, is_business_day
from bizdays.calendar import CalendarError, load_closures
from bizdays.config import DEFAULT_CONFIG, ConfigError, calendar_source, project_root


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
    check = commands.add_parser("check", help="say whether DATE is a business day")
    check.add_argument("day", type=_date)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        closures = load_closures(calendar_source(args.config), project_root(args.config))
    except (CalendarError, ConfigError) as exc:
        print(f"bizdays: {exc}", file=sys.stderr)
        return 2
    if args.command == "add":
        try:
            print(add_business_days(args.start, args.count, closures).isoformat())
        except ValueError as exc:
            print(f"bizdays: {exc}", file=sys.stderr)
            return 2
        return 0
    business = is_business_day(args.day, closures)
    print(f"{args.day.isoformat()} is {'a business day' if business else 'not a business day'}")
    return 0
