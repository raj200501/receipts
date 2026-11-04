"""Command line: ``csvsummary summary FILE`` and ``csvsummary top FILE COLUMN``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from csvsummary.reader import Table, TableError, read_table
from csvsummary.render import render_summary, render_top
from csvsummary.stats import summarize, top_values

DEFAULT_LIMIT = 10


def _delimiter(text: str) -> str:
    """``--delimiter``: one character, or the word ``tab``."""
    if text == "tab":
        return "\t"
    if len(text) != 1:
        raise argparse.ArgumentTypeError(f"expected one character or 'tab', got {text!r}")
    return text


def _limit(text: str) -> int:
    """``--limit``: a whole number of at least 1."""
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"expected a whole number of at least 1, got {text!r}")
    return int(text)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("file", type=Path, help="the CSV file")
    common.add_argument(
        "--delimiter", type=_delimiter, default=",", help="field separator (default: a comma)"
    )
    parser = argparse.ArgumentParser(prog="csvsummary", description="Summarize a CSV export.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("summary", parents=[common], help="row count and column statistics")
    top = commands.add_parser("top", parents=[common], help="most common values of a column")
    top.add_argument("column", help="the column name, as in the header row")
    top.add_argument(
        "--limit", type=_limit, default=DEFAULT_LIMIT, help="how many values to show (10)"
    )
    return parser


def _load(path: Path, delimiter: str) -> Table | None:
    """Read the file, or print why it cannot be read and return None."""
    try:
        return read_table(path, delimiter)
    except FileNotFoundError:
        print(f"csvsummary: no such file: {path}", file=sys.stderr)
    except UnicodeDecodeError:
        print(f"csvsummary: {path}: not UTF-8 text", file=sys.stderr)
    except OSError as exc:
        print(f"csvsummary: {path}: {exc.strerror}", file=sys.stderr)
    except TableError as exc:
        print(f"csvsummary: {path}: {exc}", file=sys.stderr)
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    table = _load(args.file, args.delimiter)
    if table is None:
        return 2
    if args.command == "summary":
        sys.stdout.write(render_summary(len(table.rows), summarize(table)))
        return 0
    try:
        values = table.column(args.column)
    except KeyError as exc:
        print(f"csvsummary: {exc.args[0]}", file=sys.stderr)
        return 2
    sys.stdout.write(render_top(top_values(values, args.limit)))
    return 0
