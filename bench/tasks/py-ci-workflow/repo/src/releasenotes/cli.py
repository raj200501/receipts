"""Command line interface: ``python -m releasenotes notes|bump``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from releasenotes.bump import next_version, suggest_bump
from releasenotes.commits import Commit, parse_subject
from releasenotes.grouping import group_commits
from releasenotes.render import render_markdown


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="releasenotes", description="Release notes tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    notes = commands.add_parser("notes", help="print Markdown release notes")
    notes.add_argument("--version", required=True)
    notes.add_argument("--date", required=True, help="YYYY-MM-DD")
    bump = commands.add_parser("bump", help="print the next version")
    bump.add_argument("current", help="the current MAJOR.MINOR.PATCH version")
    return parser


def _read_commits(stream) -> list[Commit]:
    """Parse one subject per line; lines that do not follow the style are skipped."""
    parsed = (parse_subject(line) for line in stream)
    return [commit for commit in parsed if commit is not None]


def main(argv: Sequence[str] | None = None, stdin=None) -> int:
    """Run the tool on subjects from ``stdin``; returns 0, or 2 for bad input."""
    parser = _build_parser()
    try:
        options = parser.parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code else 0
    commits = _read_commits(stdin if stdin is not None else sys.stdin)
    if options.command == "notes":
        print(render_markdown(options.version, options.date, group_commits(commits)), end="")
        return 0
    try:
        print(next_version(options.current, suggest_bump(commits)))
    except ValueError as err:
        print(f"releasenotes: error: {err}", file=sys.stderr)
        return 2
    return 0
