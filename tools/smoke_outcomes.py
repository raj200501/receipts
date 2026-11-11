"""Exploratory outcomes of the banked G6 smoke runs: ``artifacts/exploratory/smoke_outcomes.json``.

    python tools/smoke_outcomes.py

The smoke runs are one unmanipulated run per receipts-bench task by ``ma-qwen7b``
(Qwen2.5-Coder-7B-Instruct in minimal-agent), made to validate the benchmark and to
supply E0's material. They are not a confirmatory sample: no manipulation, one model,
one seed, and the claim verdicts are the ones the instrument gave at run time
(``run.json``), before the instrument's held-out validation (gate G5). The scaffold
changed during the smoke study (DECISIONS D39, D44 to D46); each run's code commit and
agent parameters are recorded with it. Every rate carries a Wilson 95 percent interval.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from receipts.analysis.rates import wilson_interval

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts" / "studies" / "smoke" / "runs"
OUT = ROOT / "artifacts" / "exploratory" / "smoke_outcomes.json"


def run_row(record: Mapping[str, Any]) -> dict[str, Any]:
    """One run's outcomes, from its ``run.json``."""
    prov = record.get("provenance") or {}
    params = (prov.get("agent_config") or {}).get("params") or {}
    claims = record.get("claims") or []
    verdicts = Counter(str(c.get("verdict")) for c in claims)
    task = str(record["task_id"])
    language = "typescript" if task.startswith(("ts-", "pilot-ts-")) else "python"
    return {
        "run_id": str(record["run_id"]),
        "task_id": task,
        "language": language,
        "stop_reason": str(record["stop_reason"]),
        "turns": int(record["turns"]),
        "reported": bool(str(record.get("report") or "").strip()),
        "success_reported": bool(record["success_reported"]),
        "ground_truth_success": record["ground_truth_success"],
        "false_success": bool(record["false_success"]),
        "claims": len(claims),
        "claims_by_verdict": dict(sorted(verdicts.items())),
        "claim_types": dict(sorted(Counter(str(c.get("type")) for c in claims).items())),
        "code_commit": str(prov.get("snapshot_of") or prov.get("git_sha") or ""),
        "grammar": "response_format" in params,
        "max_tokens": params.get("max_tokens"),
    }


def rate(successes: int, n: int) -> dict[str, Any]:
    """A proportion with its Wilson 95 percent interval (null when n is 0)."""
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci_low": None, "ci_high": None}
    low, high = wilson_interval(successes, n)
    return {"k": successes, "n": n, "rate": successes / n, "ci_low": low, "ci_high": high}


def summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run-level rates and claim-level counts over ``rows``."""
    with_truth = [r for r in rows if r["ground_truth_success"] is not None]
    reported = [r for r in with_truth if r["reported"]]
    claimed = [r for r in reported if r["success_reported"]]
    verdicts: Counter[str] = Counter()
    for r in rows:
        verdicts.update(r["claims_by_verdict"])
    contradicted_runs = sum(1 for r in reported if r["claims_by_verdict"].get("contradicted"))
    return {
        "runs": len(rows),
        "runs_with_hidden_checks": len(with_truth),
        "runs_with_report": len(reported),
        "task_success": rate(
            sum(1 for r in with_truth if r["ground_truth_success"]), len(with_truth)
        ),
        "success_claimed": rate(len(claimed), len(reported)),
        "false_success": rate(sum(1 for r in reported if r["false_success"]), len(reported)),
        "success_claims_false": rate(sum(1 for r in claimed if r["false_success"]), len(claimed)),
        "any_contradicted": rate(contradicted_runs, len(reported)),
        "claims": sum(verdicts.values()),
        "claims_by_verdict": dict(sorted(verdicts.items())),
        "turn_cap_reached": sum(1 for r in rows if r["stop_reason"] == "finished_at_cap"),
        "by_language": {
            lang: len([r for r in rows if r["language"] == lang])
            for lang in sorted({str(r["language"]) for r in rows})
        },
    }


def provenance(paths: Sequence[Path]) -> dict[str, Any]:
    """Git SHA, command, time, and the SHA-256 of every run record read."""
    sha = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "git_sha": sha,
        "command": " ".join([Path(sys.executable).name, *sys.argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": {
            (str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in paths
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write the exploratory smoke-outcomes artifact."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=RUNS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    paths = sorted(args.runs.glob("*/run.json"))
    records = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    if not records:
        print(f"no banked runs under {args.runs}", file=sys.stderr)
        return 2
    if any(r.get("synthetic") for r in records):
        print("a run record is marked synthetic; refusing", file=sys.stderr)
        return 2
    rows = [run_row(r) for r in records]
    totals = summary(rows)
    artifact: dict[str, Any] = {
        "schema": "receipts.exploratory.smoke_outcomes/1",
        "exploratory": True,
        "confirmatory": False,
        "synthetic": False,
        "note": (
            "G6 smoke runs: one unmanipulated run per task by ma-qwen7b, one seed. Claim "
            "verdicts are the run-time instrument's, before its held-out validation (G5). "
            "The scaffold changed during the study (D39, D44 to D46); see each run's "
            "code_commit and grammar fields. Not a confirmatory result."
        ),
        "summary": totals,
        "runs": rows,
        "provenance": provenance(paths),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    false = totals["false_success"]
    print(
        f"smoke outcomes: {totals['runs']} runs, false success {false['k']}/{false['n']}; "
        f"written to {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
