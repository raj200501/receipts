"""Command line: ``timesheet report FILE [--project NAME]``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from timesheet.entries import EntryError, read_entries
from timesheet.report import render
from timesheet.weeks import totals_by_week


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(prog="timesheet", description="Weekly hour totals.")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="print weekly totals per project")
    report.add_argument("file", type=Path, help="CSV export of work entries")
    report.add_argument("--project", help="only show this project")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        entries = read_entries(args.file)
    except FileNotFoundError:
        print(f"timesheet: no such file: {args.file}", file=sys.stderr)
        return 2
    except EntryError as exc:
        print(f"timesheet: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(totals_by_week(entries), args.project))
    return 0
