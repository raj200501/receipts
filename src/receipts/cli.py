"""The ``receipts`` command line.

- ``receipts check LEDGER [--report FILE] [--json]``: extract the claims in a final report
  (by default the ``run_end`` report recorded in the ledger) and print each verdict with
  its evidence.
- ``receipts facts LEDGER``: print the ledger as a plain-text fact sheet.
- ``receipts wrap --workspace DIR --test-cmd CMD -- <agent command>``: run another agent
  CLI and annotate its final report (see :mod:`receipts.hook.wrap`).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


def _check(args: argparse.Namespace) -> int:
    from receipts.claims.extract import extract_claims
    from receipts.hook.wrap import annotate
    from receipts.ledger.events import Ledger
    from receipts.verify import verify_run

    ledger = Ledger.load(args.ledger)
    report = args.report.read_text(encoding="utf-8") if args.report else ledger.final_report()
    if report is None:
        print("receipts: no report given and the ledger has no run_end report", file=sys.stderr)
        return 2
    verification = verify_run(extract_claims(report), ledger, report=report)
    if args.json:
        print(json.dumps(verification.to_dict(), indent=2))
    else:
        sys.stdout.write(annotate(verification).lstrip("\n"))
    return 1 if verification.counts()["contradicted"] else 0


def _facts(args: argparse.Namespace) -> int:
    from receipts.evaluation.facts import fact_sheet
    from receipts.ledger.events import Ledger

    sys.stdout.write(fact_sheet(Ledger.load(args.ledger), include_report=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``receipts``. ``check`` exits 1 when any claim is contradicted."""
    parser = argparse.ArgumentParser(prog="receipts", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a final report against a ledger")
    check.add_argument("ledger", type=Path)
    check.add_argument("--report", type=Path, default=None)
    check.add_argument("--json", action="store_true")
    facts = sub.add_parser("facts", help="print a ledger as a fact sheet")
    facts.add_argument("ledger", type=Path)
    sub.add_parser("wrap", help="run an agent CLI and annotate its report", add_help=False)
    args, rest = parser.parse_known_args(argv)
    if args.command == "wrap":
        from receipts.hook.wrap import main as wrap_main

        return wrap_main(rest)
    if rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
    return _check(args) if args.command == "check" else _facts(args)


if __name__ == "__main__":
    sys.exit(main())
