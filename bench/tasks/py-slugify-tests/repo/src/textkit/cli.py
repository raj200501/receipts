"""Command line: ``textkit slug`` and ``textkit unique``.

``textkit slug TITLE...`` prints the slug of each title; ``-`` reads titles from standard
input, one per line. ``textkit unique`` reads titles from standard input and prints their
slugs, numbering the repeated ones. Every error is printed to stderr as
``textkit: error: ...`` and the command exits with status 2.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from textkit.slugify import slugify
from textkit.unique import unique_slug


def build_parser() -> argparse.ArgumentParser:
    """The argument parser of the command line."""
    parser = argparse.ArgumentParser(prog="textkit", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    slug = sub.add_parser("slug", help="print the slug of each title")
    slug.add_argument("titles", nargs="+", metavar="TITLE")
    slug.add_argument("--separator", default="-")
    slug.add_argument("--max-length", type=int, default=None)
    slug.add_argument("--stopwords", default="", help="comma-separated words to leave out")
    unique = sub.add_parser("unique", help="print unique slugs for the titles on stdin")
    unique.add_argument("--separator", default="-")
    unique.add_argument("--max-length", type=int, default=None)
    return parser


def _stdin_titles() -> list[str]:
    return [line.rstrip("\n") for line in sys.stdin]


def run_slug(args: argparse.Namespace) -> int:
    titles = _stdin_titles() if args.titles == ["-"] else args.titles
    stopwords = [word for word in args.stopwords.split(",") if word]
    for title in titles:
        print(
            slugify(
                title,
                separator=args.separator,
                max_length=args.max_length,
                stopwords=stopwords,
            )
        )
    return 0


def run_unique(args: argparse.Namespace) -> int:
    taken: set[str] = set()
    for title in _stdin_titles():
        slug = unique_slug(title, taken, separator=args.separator, max_length=args.max_length)
        taken.add(slug)
        print(slug)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; return the exit status."""
    args = build_parser().parse_args(argv)
    try:
        return {"slug": run_slug, "unique": run_unique}[args.command](args)
    except ValueError as exc:
        print(f"textkit: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
