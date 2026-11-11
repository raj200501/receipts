"""The ``stockroom`` command line: ``process`` an order file."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from stockroom.catalog import CatalogError, load_catalog
from stockroom.orders import OrderError, process_order
from stockroom.receipt import format_receipt
from stockroom.stock import StockError, load_stock, save_stock


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(prog="stockroom", description="Process shop orders.")
    commands = parser.add_subparsers(dest="command", required=True)
    process = commands.add_parser("process", help="price an order and reserve its stock")
    process.add_argument("order", metavar="ORDER.json")
    process.add_argument("--catalog", default="data/catalog.json", metavar="FILE")
    process.add_argument("--stock", default="data/stock.json", metavar="FILE")
    process.add_argument("--today", metavar="YYYY-MM-DD", help="the day to check coupons against")
    process.add_argument("--commit", action="store_true", help="write the new stock levels back")
    return parser


def _error(message: str) -> int:
    print(f"stockroom: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command. Exit status: 0 done, 1 order rejected, 2 bad input or files."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        return _error(f"not a date: {args.today!r}")
    try:
        order = json.loads(Path(args.order).read_text(encoding="utf-8"))
    except OSError as exc:
        return _error(f"cannot read {args.order}: {exc.strerror or exc}")
    except ValueError as exc:
        return _error(f"{args.order} is not valid JSON: {exc}")
    if not isinstance(order, dict):
        return _error(f"{args.order} must hold one order object")
    try:
        catalog = load_catalog(args.catalog)
        stock = load_stock(args.stock)
    except (CatalogError, StockError) as exc:
        return _error(str(exc))
    try:
        receipt = process_order(order, catalog, stock, today)
    except OrderError as exc:
        label = order.get("id") if isinstance(order.get("id"), str) else args.order
        for problem in exc.problems:
            print(f"stockroom: {label}: {problem}", file=sys.stderr)
        return 1
    sys.stdout.write(format_receipt(receipt))
    if args.commit:
        save_stock(stock, args.stock)
    return 0
