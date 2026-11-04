"""Command line: ``thumbconf [--config PATH] show|get KEY|check``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from thumbconf.loader import DEFAULT_PATH, load_config
from thumbconf.settings import BY_KEY
from thumbconf.values import ConfigError, format_value


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(
        prog="thumbconf", description="The effective configuration of thumbd."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_PATH,
        help=f"the configuration file (default: {DEFAULT_PATH})",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="print every setting with its value")
    get = commands.add_parser("get", help="print the value of one setting")
    get.add_argument("key", help="the setting, as section.key")
    commands.add_parser("check", help="check the configuration and say whether it is usable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    if args.command == "get" and args.key not in BY_KEY:
        print(f"thumbconf: unknown setting {args.key}", file=sys.stderr)
        return 2
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"thumbconf: {exc}", file=sys.stderr)
        return 2
    if args.command == "show":
        for key, value in config.items():
            print(f"{key} = {format_value(value)}")
    elif args.command == "get":
        print(format_value(config[args.key]))
    else:
        print(f"{args.config}: ok")
    return 0
