"""Command line: ``invoicer totals FILE [--invoice NUMBER]`` and ``invoicer list FILE``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from invoicer.items import ItemError, read_items
from invoicer.report import render, render_list
from invoicer.totals import InvoiceTotals, invoice_totals


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(
        prog="invoicer", description="Invoice totals from the order system's CSV export."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    totals = commands.add_parser("totals", help="print every invoice with its lines and totals")
    totals.add_argument("file", type=Path, help="CSV export of invoice lines")
    totals.add_argument("--invoice", metavar="NUMBER", help="only print this invoice")
    listing = commands.add_parser("list", help="print one line per invoice with its total")
    listing.add_argument("file", type=Path, help="CSV export of invoice lines")
    return parser


def _load(path: Path) -> list[InvoiceTotals]:
    return invoice_totals(read_items(path))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        invoices = _load(args.file)
    except FileNotFoundError:
        print(f"invoicer: no such file: {args.file}", file=sys.stderr)
        return 2
    except ItemError as exc:
        print(f"invoicer: {exc}", file=sys.stderr)
        return 2
    if args.command == "list":
        sys.stdout.write(render_list(invoices))
        return 0
    if args.invoice is not None:
        invoices = [invoice for invoice in invoices if invoice.invoice == args.invoice]
        if not invoices:
            print(f"invoicer: no invoice {args.invoice} in {args.file}", file=sys.stderr)
            return 2
    sys.stdout.write(render(invoices))
    return 0
