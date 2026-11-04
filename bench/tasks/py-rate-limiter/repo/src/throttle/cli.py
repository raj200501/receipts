"""Command line: ``throttle replay LOG`` and ``throttle limits``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from throttle.policy import DEFAULT_CONFIG, Policy, PolicyError, load_policy
from throttle.replay import LogError, read_log, render_report, replay


def build_parser() -> argparse.ArgumentParser:
    """The argument parser."""
    parser = argparse.ArgumentParser(
        prog="throttle", description="Per-client rate limits for the API gateway."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="the limits file (default: config/limits.toml)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    replaying = commands.add_parser("replay", help="replay a request log, count the decisions")
    replaying.add_argument("log", type=Path, help="CSV request log: time,client,method,path")
    replaying.add_argument(
        "--rejected", action="store_true", help="also list every rejected request"
    )
    commands.add_parser("limits", help="print the default limit and every listed client's")
    return parser


def render_limits(policy: Policy) -> str:
    """One line per limit: the default first, then the listed clients by name."""
    rows = [("(default)", policy.default), *sorted(policy.clients.items())]
    width = max(len("client"), *(len(name) for name, _ in rows))
    lines = [f"{'client':<{width}}  {'burst':>5}  {'per_minute':>10}"]
    lines.extend(f"{name:<{width}}  {lim.burst:>5}  {lim.per_minute:>10}" for name, lim in rows)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        policy = load_policy(args.config)
    except PolicyError as exc:
        print(f"throttle: {exc}", file=sys.stderr)
        return 2
    if args.command == "limits":
        sys.stdout.write(render_limits(policy))
        return 0
    try:
        requests = read_log(args.log)
    except FileNotFoundError:
        print(f"throttle: no such file: {args.log}", file=sys.stderr)
        return 2
    except LogError as exc:
        print(f"throttle: {args.log}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render_report(replay(requests, policy), rejected=args.rejected))
    return 0
