"""Copy banked study runs into the offline demo's recorded fixtures (gate G4).

Usage::

    python tools/record_demo.py artifacts/studies/pilot/runs/<run_id> [...]

Each run's ``ledger.jsonl`` is copied byte for byte to
``tests/fixtures/recorded/demo/<run_id>/`` with a ``meta.json`` that names the banked run
it came from, the agent, the model, the commit the run executed under, and the ledger's
SHA-256, so anyone can confirm the fixture is the banked run unchanged. Only real runs
are accepted: the run must have a ``run.json`` whose provenance records a git SHA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "recorded" / "demo"


def fixture_meta(run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    """The ``meta.json`` for one banked run (raises ValueError if it is not a real run)."""
    record_path = run_dir / "run.json"
    ledger = run_dir / "ledger.jsonl"
    if not record_path.is_file() or not ledger.is_file():
        raise ValueError(f"{run_dir}: not a banked run (needs run.json and ledger.jsonl)")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    sha = record.get("provenance", {}).get("git_sha")
    if not sha:
        raise ValueError(f"{run_dir}: run.json has no provenance git_sha")
    first = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    if first.get("kind") != "run_start":
        raise ValueError(f"{run_dir}: the ledger does not start with run_start")
    try:
        source = run_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"{run_dir}: banked runs must live inside the repository") from None
    return {
        "run_id": record["run_id"],
        "task_id": record["task_id"],
        "agent": first["data"]["agent"],
        "config_id": record["config_id"],
        "model": record["model"],
        "recorded_from": f"{source} (run at {sha[:12]})",
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "note": "copied from a real banked run by tools/record_demo.py; not synthetic",
    }


def record(run_dir: Path, fixtures: Path = FIXTURES, root: Path = ROOT) -> Path:
    """Copy one banked run into ``fixtures`` and return the fixture directory."""
    meta = fixture_meta(run_dir, root)
    target = fixtures / str(meta["run_id"])
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copyfile(run_dir / "ledger.jsonl", target / "ledger.jsonl")
    (target / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def main(argv: Sequence[str] | None = None) -> int:
    """Record every named run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    for run_dir in args.runs:
        print(record(run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
