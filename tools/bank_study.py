"""Bank a study's runs into the artifacts the gates read.

    python tools/bank_study.py smoke   # smoke_runs.json (G6) and claim_type_counts.json (G5)
    python tools/bank_study.py e1      # artifacts/e1/runs.jsonl
    python tools/bank_study.py pilot   # artifacts/studies/pilot/summary.json (planning)

Reads only banked ``artifacts/studies/<study>/runs/*/run.json`` files and writes the
derived artifacts with provenance (git SHA, the command, the time, and the SHA-256 of the
study plan the runs came from).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from receipts.study import aggregate

ROOT = Path(__file__).resolve().parents[1]


def provenance(study: str) -> dict[str, str]:
    """Provenance for an artifact derived from ``study``'s banked runs."""
    sha = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    plan = ROOT / "artifacts" / "studies" / study / "plan.json"
    return {
        "git_sha": sha,
        "command": " ".join([sys.executable, *sys.argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else "",
        "study": study,
    }


def write_json(path: Path, data: object) -> None:
    """Write a JSON artifact with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Derive the gate artifacts for one study."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("study", choices=("smoke", "e1", "pilot"))
    args = parser.parse_args(argv)
    runs = ROOT / "artifacts" / "studies" / args.study / "runs"
    records = aggregate.load_records(runs)
    prov = provenance(args.study)
    if args.study == "smoke":
        write_json(
            ROOT / "artifacts/bench/smoke_runs.json", aggregate.smoke_runs_artifact(records, prov)
        )
        write_json(
            ROOT / "artifacts/e0/claim_type_counts.json",
            aggregate.claim_type_counts_artifact(records, prov),
        )
    elif args.study == "pilot":
        write_json(
            ROOT / "artifacts/studies/pilot/summary.json",
            aggregate.pilot_summary_artifact(records, prov),
        )
    else:
        aggregate.write_jsonl(ROOT / "artifacts/e1/runs.jsonl", aggregate.e1_rows(records))
    print(f"{args.study}: banked {len(records)} run(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
