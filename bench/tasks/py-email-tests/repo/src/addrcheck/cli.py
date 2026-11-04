"""Command line interface: ``python -m addrcheck [options] ADDRESS...``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from addrcheck.errors import REASONS
from addrcheck.validator import check


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="addrcheck", description="Check email addresses.")
    parser.add_argument("addresses", nargs="*", metavar="ADDRESS", help="'-' reads stdin")
    parser.add_argument("--block", action="append", default=[], metavar="DOMAIN")
    parser.add_argument("--no-plus", action="store_true", help="reject name+tag addresses")
    parser.add_argument("--list-reasons", action="store_true")
    return parser


def _read_addresses(args: Sequence[str]) -> list[str]:
    found: list[str] = []
    for item in args:
        if item == "-":
            found.extend(line.rstrip("\n") for line in sys.stdin)
        else:
            found.append(item)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool; returns 0 when every address is valid, 1 when one is not, 2 on misuse."""
    parser = _build_parser()
    try:
        options = parser.parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code else 0
    if options.list_reasons:
        for code, text in REASONS.items():
            print(f"{code}: {text}")
        return 0
    if not options.addresses:
        print("addrcheck: error: no address given", file=sys.stderr)
        return 2
    status = 0
    for address in _read_addresses(options.addresses):
        verdict = check(address, blocked_domains=options.block, allow_plus_tags=not options.no_plus)
        if verdict.ok:
            print(f"ok {verdict.normalized}")
        else:
            print(f"invalid {address!r}: {verdict.reason}")
            status = 1
    return status
