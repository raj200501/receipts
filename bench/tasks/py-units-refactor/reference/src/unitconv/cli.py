"""Command line: ``unitconv convert``, ``unitconv batch``, and ``unitconv units``."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

from unitconv.aliases import normalize_unit
from unitconv.conversions import convert, units_by_dimension
from unitconv.errors import UnitError
from unitconv.quantity import format_number, parse_quantity

#: Decimal places used to echo the value that was converted.
INPUT_PRECISION = 6


def _precision(text: str) -> int:
    try:
        places = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if not 0 <= places <= 12:
        raise argparse.ArgumentTypeError(f"must be from 0 to 12, got {places}")
    return places


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(prog="unitconv", description="Convert between units.")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("convert", help="convert one value")
    one.add_argument("value", help="the number to convert, for example 12.5")
    one.add_argument("source", help="its unit, as a symbol or a name (ft, feet)")
    one.add_argument("target", help="the unit to convert to")
    one.add_argument("--precision", type=_precision, default=4, help="decimal places (4)")
    batch = commands.add_parser("batch", help="convert every quantity in a text file")
    batch.add_argument("file", type=Path, help="one quantity per line, such as 12 lb")
    batch.add_argument("--to", dest="target", required=True, help="the unit to convert to")
    batch.add_argument("--precision", type=_precision, default=4, help="decimal places (4)")
    commands.add_parser("units", help="list the units of the conversion table")
    return parser


def parse_number(text: str) -> float:
    """The number in ``text``; raises UnitError when it is not a finite number."""
    try:
        number = float(text)
    except ValueError:
        raise UnitError(f"not a number: {text!r}") from None
    if not math.isfinite(number):
        raise UnitError(f"not a number: {text!r}")
    return number


def conversion_line(value: float, source: str, target: str, precision: int) -> str:
    """One line of output, such as ``12 ft = 3.6576 m`` (units are symbols)."""
    result = convert(value, source, target)
    shown = format_number(value, INPUT_PRECISION)
    return f"{shown} {source} = {format_number(result, precision)} {target}"


def run_convert(value: str, source: str, target: str, precision: int) -> list[str]:
    """The output lines of ``unitconv convert``."""
    number = parse_number(value)
    return [conversion_line(number, normalize_unit(source), normalize_unit(target), precision)]


def run_batch(path: Path, target: str, precision: int) -> list[str]:
    """The output lines of ``unitconv batch``: one per quantity in the file.

    Raises:
        UnitError: a line cannot be converted; the message starts with its line number.
    """
    unit = normalize_unit(target)
    lines: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        try:
            value, source = parse_quantity(text)
            lines.append(conversion_line(value, source, unit, precision))
        except UnitError as exc:
            raise UnitError(f"line {number}: {exc}") from None
    return lines


def run_units() -> list[str]:
    """The output lines of ``unitconv units``: one line per dimension, in table order."""
    return [
        f"{dimension}: {' '.join(symbols)}" for dimension, symbols in units_by_dimension().items()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "convert":
            lines = run_convert(args.value, args.source, args.target, args.precision)
        elif args.command == "batch":
            lines = run_batch(args.file, args.target, args.precision)
        else:
            lines = run_units()
    except FileNotFoundError:
        print(f"unitconv: no such file: {args.file}", file=sys.stderr)
        return 2
    except UnitError as exc:
        print(f"unitconv: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    return 0
