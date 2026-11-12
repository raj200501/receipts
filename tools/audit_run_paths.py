"""Report every agent action in a run's ledger that named a path outside its workspace.

    python tools/audit_run_paths.py RUN_DIR [RUN_DIR ...] [--json]

Each RUN_DIR is a run's directory (holding ``ledger.jsonl``, and ``run.json`` once the
run is banked) or its ledger file. The audit (:mod:`receipts.study.audit`, which lists
what it reports and what it cannot see) reads the ledgers and writes nothing, so it may
read a run that is still in progress. Runs made before the study sandbox hid the
checkout (review N18, DECISIONS D67) are audited this way before banking.

Exit status: 0 when every run is clean, 1 when anything was found in a run or a ledger
could not be read whole, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from receipts.study.audit import audit_ledger, format_audit


def main(argv: Sequence[str] | None = None) -> int:
    """Audit each run named on the command line and print the result."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, metavar="RUN_DIR")
    parser.add_argument("--json", action="store_true", help="print the audits as JSON")
    args = parser.parse_args(argv)
    audits = [audit_ledger(path) for path in args.runs]
    if args.json:
        print(json.dumps([audit.to_dict() for audit in audits], indent=2))
    else:
        for audit in audits:
            print("\n".join(format_audit(audit)))
        dirty = sum(1 for audit in audits if not audit.clean)
        clean = len(audits) - dirty
        print(f"audited {len(audits)} run(s): {clean} clean, {dirty} with findings")
    return 0 if all(audit.clean for audit in audits) else 1


if __name__ == "__main__":
    sys.exit(main())
