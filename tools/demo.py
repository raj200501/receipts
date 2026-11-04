"""``make demo``: the offline demo over recorded runs (gate G4).

Every run under ``tests/fixtures/recorded/demo/`` is a copy of a real, recorded agent run
(its ``meta.json`` names the banked run it was copied from, the model, and the commit).
For each run the demo prints the task, the agent's final report, every claim receipts
extracted with its verdict and the evidence in one sentence, and the run summary. It
makes no model calls and needs no network: claims come from the deterministic pattern
extractor and verdicts from the recorded ledger. Output is deterministic (no times or
paths), so ``--check`` compares it with ``tests/golden/demo_output.txt``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded" / "demo"
GOLDEN = ROOT / "tests" / "golden" / "demo_output.txt"
MARK = {"supported": "SUPPORTED   ", "contradicted": "CONTRADICTED", "unverifiable": "UNVERIFIABLE"}


def render_run(run_dir: Path) -> str:
    """The demo text for one recorded run."""
    from receipts.claims.extract import extract_claims

    from receipts.ledger.events import Ledger
    from receipts.verify import verify_run

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    ledger = Ledger.load(run_dir / "ledger.jsonl")
    report = ledger.final_report() or ""
    claims = extract_claims(report)
    verification = verify_run(claims, ledger, report=report)
    lines = [
        f"=== {meta['task_id']} | {meta['agent']} ({meta['model']})",
        f"    recorded from {meta['recorded_from']}",
        "Final report:",
        *("  " + line for line in report.strip().splitlines()),
        "receipts:",
    ]
    for claim, verdict in zip(verification.claims, verification.verdicts, strict=True):
        lines.append(f"  [{MARK[verdict.label.value]}] {claim.type.value}: {claim.text.strip()}")
        lines.append(f"      {verdict.reason}")
    if not verification.claims:
        lines.append("  no checkable claims")
    for omission in verification.omissions:
        lines.append(f"  [NOT MENTIONED] {omission.detail}")
    truth = verification.ground_truth_success
    lines.append(
        f"Summary: success reported={verification.success_reported}, hidden checks passed="
        f"{'n/a' if truth is None else truth}, false success={verification.false_success}"
    )
    return "\n".join(lines) + "\n"


def render_all(fixtures: Path = FIXTURES) -> str:
    """The full demo output over every recorded run, in name order."""
    runs = sorted(p for p in fixtures.iterdir() if (p / "ledger.jsonl").is_file())
    if not runs:
        raise SystemExit(f"demo: no recorded runs under {fixtures}")
    header = (
        "receipts offline demo: recorded agent runs checked claim by claim "
        "(no network, no model calls)\n\n"
    )
    return header + "\n".join(render_run(run) for run in runs)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the demo, or with ``--check`` compare it with the golden output."""
    parser = argparse.ArgumentParser(description="Offline demo over recorded runs.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-golden", action="store_true")
    args = parser.parse_args(argv)
    os.environ["RECEIPTS_OFFLINE"] = "1"
    output = render_all()
    if args.write_golden:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(output, encoding="utf-8")
    if args.check:
        golden = GOLDEN.read_text(encoding="utf-8") if GOLDEN.is_file() else ""
        if output != golden:
            sys.stdout.writelines(
                difflib.unified_diff(
                    golden.splitlines(keepends=True),
                    output.splitlines(keepends=True),
                    "golden",
                    "demo",
                )
            )
            print("DEMO: FAIL output differs from tests/golden/demo_output.txt")
            return 1
        print("DEMO: PASS output matches tests/golden/demo_output.txt")
        return 0
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
