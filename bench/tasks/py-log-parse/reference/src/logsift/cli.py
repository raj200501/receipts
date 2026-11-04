"""The ``logsift`` command line: ``show`` and ``summary``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from logsift.entries import LEVELS, Entry
from logsift.filters import Filter, apply
from logsift.hosts import DEFAULT_PATH, HostOffsets, HostOffsetsError
from logsift.parse import read_log
from logsift.report import format_entry, summarize
from logsift.timefmt import TimeFormatError, parse_bound


def build_parser() -> argparse.ArgumentParser:
    """The argument parser; both commands take the same filters."""
    parser = argparse.ArgumentParser(prog="logsift", description="Filtered views of app logs.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("show", "print matching entries"), ("summary", "count matching entries")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("files", nargs="+", metavar="FILE")
        sub.add_argument("--since", metavar="TIME", help="keep entries at or after TIME")
        sub.add_argument("--until", metavar="TIME", help="keep entries before TIME")
        sub.add_argument("--host", metavar="HOST")
        sub.add_argument("--component", metavar="NAME")
        sub.add_argument("--min-level", metavar="LEVEL", help="keep entries at LEVEL or worse")
        sub.add_argument(
            "--host-offsets",
            metavar="FILE",
            default=DEFAULT_PATH,
            help=f"UTC offsets of the pay-batch hosts (default: {DEFAULT_PATH})",
        )
    return parser


def _error(message: str) -> int:
    print(f"logsift: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; return the exit status (0 ok, 2 for bad input or unreadable files)."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        since = parse_bound(args.since) if args.since else None
        until = parse_bound(args.until) if args.until else None
    except TimeFormatError as exc:
        return _error(str(exc))
    min_level = None
    if args.min_level is not None:
        min_level = args.min_level.upper()
        if min_level not in LEVELS:
            return _error(f"unknown level {args.min_level!r} (expected one of {', '.join(LEVELS)})")
    flt = Filter(
        since=since, until=until, host=args.host, component=args.component, min_level=min_level
    )
    offsets = HostOffsets(args.host_offsets)
    entries: list[Entry] = []
    for path in args.files:
        try:
            found, problems = read_log(path, offsets)
        except OSError as exc:
            return _error(f"cannot read {path}: {exc.strerror or exc}")
        except HostOffsetsError as exc:
            return _error(f"host offsets: {exc}")
        for problem in problems:
            print(f"logsift: {problem}", file=sys.stderr)
        entries.extend(found)
    selected = apply(entries, flt)
    if args.command == "show":
        for entry in selected:
            print(format_entry(entry))
    else:
        sys.stdout.write(summarize(selected))
    return 0
