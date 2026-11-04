"""Command line: ``pinwatch status``, ``pinwatch check``, and ``pinwatch latest``.

Every error is printed to stderr as ``pinwatch: error: ...`` and the command exits with
status 2. ``check`` exits with status 1 when a pin is outside its policy.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import tinyver

from pinwatch.errors import PinwatchError
from pinwatch.pins import load_pins
from pinwatch.policy import allows, load_policy
from pinwatch.releases import latest_release, load_releases
from pinwatch.report import Row, format_status, format_violation, show

DEFAULT_PINS = "data/pins.json"
DEFAULT_RELEASES = "data/releases.json"
DEFAULT_POLICY = "data/policy.json"


def build_parser() -> argparse.ArgumentParser:
    """The argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="pinwatch", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("status", "show pinned and latest versions of every component"),
        ("check", "exit with status 1 when a pin is outside its policy"),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--pins", default=DEFAULT_PINS)
        command.add_argument("--releases", default=DEFAULT_RELEASES)
        command.add_argument("--policy", default=DEFAULT_POLICY)
    latest = sub.add_parser("latest", help="print the newest release of a component")
    latest.add_argument("component")
    latest.add_argument("--pre", action="store_true", help="count prereleases too")
    latest.add_argument("--releases", default=DEFAULT_RELEASES)
    return parser


def status_rows(pins_path: str, releases_path: str, policy_path: str) -> list[Row]:
    """The status of every pinned component, in the order of the pin file."""
    pins = load_pins(pins_path)
    releases = load_releases(releases_path)
    policy = load_policy(policy_path)
    rows = []
    for component, pinned in pins.items():
        # A pin on a prerelease follows the prerelease track.
        newest = latest_release(releases, component, prereleases=tinyver.is_prerelease(pinned))
        requirement = policy.get(component)
        if requirement is not None and not allows(pinned, requirement):
            state = "outside policy"
        elif newest is None:
            state = "unknown"
        elif tinyver.compare(pinned, newest) < 0:
            state = "behind"
        else:
            state = "current"
        rows.append(Row(component, pinned, newest, state))
    return rows


def run_status(args: argparse.Namespace) -> int:
    for line in format_status(status_rows(args.pins, args.releases, args.policy)):
        print(line)
    return 0


def run_check(args: argparse.Namespace) -> int:
    pins = load_pins(args.pins)
    policy = load_policy(args.policy)
    violations = [
        format_violation(component, pinned, policy[component])
        for component, pinned in pins.items()
        if component in policy and not allows(pinned, policy[component])
    ]
    for line in violations:
        print(line)
    if not violations:
        print("all pins are within the policy")
    return 1 if violations else 0


def run_latest(args: argparse.Namespace) -> int:
    newest = latest_release(load_releases(args.releases), args.component, prereleases=args.pre)
    if newest is None:
        raise PinwatchError(f"no releases of {args.component!r} in {args.releases}")
    print(show(newest))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; return the exit status."""
    args = build_parser().parse_args(argv)
    handlers = {"status": run_status, "check": run_check, "latest": run_latest}
    try:
        return handlers[args.command](args)
    except PinwatchError as exc:
        print(f"pinwatch: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
