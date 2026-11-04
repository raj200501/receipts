"""Turn banked runs into the artifacts the ship gates read (docs/PLAN.md, artifact contract).

- :func:`smoke_runs_artifact`: ``artifacts/bench/smoke_runs.json`` (G6): one row per
  real, non-synthetic agent run per task.
- :func:`claim_type_counts_artifact`: ``artifacts/e0/claim_type_counts.json`` (G5): how
  often each claim type appears in real smoke-run reports, with the source run ids.
- :func:`e1_rows`: ``artifacts/e1/runs.jsonl`` (G7, G8): one row per run with its arm,
  family, task, conditions, inclusion flag, outcomes, and claims with verdicts.

Every function reads only banked ``run.json`` files.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def load_records(runs_dir: Path) -> list[dict[str, Any]]:
    """Every banked ``run.json`` under ``runs_dir``, sorted by run id."""
    records = [json.loads(path.read_text(encoding="utf-8")) for path in runs_dir.glob("*/run.json")]
    return sorted(records, key=lambda r: str(r["run_id"]))


def smoke_runs_artifact(
    records: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """The G6 smoke-run artifact: these are real model runs, so ``synthetic`` is False."""
    runs = [
        {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "agent": f"minimal-agent/{r['model']}",
            "config_id": r["config_id"],
            "stop_reason": r["stop_reason"],
            "turns": r["turns"],
            "synthetic": False,
        }
        for r in records
    ]
    return {"schema": "receipts.bench.smoke_runs/1", "runs": runs, "provenance": dict(provenance)}


def claim_type_counts_artifact(
    records: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """Claim-type frequencies over the real reports of ``records`` (G5 top five)."""
    counts: Counter[str] = Counter()
    sources = []
    for record in records:
        claims = record.get("claims", [])
        if claims:
            sources.append(str(record["run_id"]))
        counts.update(str(c["type"]) for c in claims)
    return {
        "schema": "receipts.e0.claim_type_counts/1",
        "source": "smoke-run final reports, pattern extractor",
        "counts": dict(sorted(counts.items())),
        "source_runs": sources,
        "provenance": dict(provenance),
    }


def e1_rows(
    records: Iterable[Mapping[str, Any]], valid_types: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """One row per run. ``included`` follows the preregistered rule: non-empty report.

    ``any_contradicted`` counts only claim types in ``valid_types`` (the types that met
    the G5 thresholds) when given.
    """
    valid = None if valid_types is None else set(valid_types)
    rows = []
    for r in records:
        claims = [
            {"claim_id": c["claim_id"], "claim_type": c["type"], "verdict": c["verdict"]}
            for c in r.get("claims", [])
        ]
        counted = [c for c in claims if valid is None or c["claim_type"] in valid]
        report = str(r.get("report", ""))
        rows.append(
            {
                "run_id": r["run_id"],
                "config_id": r["config_id"],
                "model": r["model"],
                "model_family": r["family"],
                "task_id": r["task_id"],
                "conditions": dict(r.get("conditions", {})),
                "seed": r["seed"],
                "synthetic": False,
                "included": bool(report.strip()),
                "completed": r["stop_reason"] == "finished" and bool(report.strip()),
                "false_success": bool(r["false_success"]),
                "success_reported": bool(r["success_reported"]),
                "ground_truth_success": r["ground_truth_success"],
                "any_contradicted": any(c["verdict"] == "contradicted" for c in counted),
                "omissions": int(r.get("omissions", 0)),
                "claims": claims,
            }
        )
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write rows as JSONL with sorted keys (stable diffs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
