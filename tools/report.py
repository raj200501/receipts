"""``make report`` and ``make reproduce``: numbers, figures, and their manifest.

- ``python tools/report.py`` writes ``artifacts/report/numbers.json``, the SVG figures,
  and ``artifacts/report/manifest.json`` from banked artifacts only.
- ``--numbers-only --out PATH`` rebuilds just the registry into PATH (``make freshness``).
- ``--reproduce`` rebuilds everything in a temporary directory and fails if any
  committed output differs.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from receipts.report.build import build, numbers_only, reproduce
from receipts.report.spec import SPEC

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    """Build, rebuild the registry only, or check reproducibility."""
    parser = argparse.ArgumentParser(description="Build report outputs from artifacts.")
    parser.add_argument("--numbers-only", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--reproduce", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.numbers_only:
        if args.out is None:
            parser.error("--numbers-only needs --out")
        numbers = numbers_only(args.root, SPEC, args.out)
        print(f"report: {len(numbers)} number(s) rebuilt into {args.out}")
        return 0
    if args.reproduce:
        problems = reproduce(args.root, SPEC)
        for problem in problems:
            print(f"problem: {problem}")
        print("REPRODUCE: " + ("PASS" if not problems else f"FAIL {len(problems)}"))
        return 0 if not problems else 1
    manifest = build(args.root, SPEC)
    figures = manifest["figures"]
    count = len(figures) if isinstance(figures, list) else 0
    print(f"report: {manifest['numbers']} number(s), {count} figure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
