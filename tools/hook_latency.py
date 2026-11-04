"""Measure receipts-hook's added latency on recorded sessions (gate G9).

For each recorded run under the given study directories, this replays the Claude Code
Stop hook exactly as Claude Code would call it: a fresh ``python -m receipts.hook stop``
process with the documented Stop payload on stdin (``last_assistant_message`` set to the
run's final report) and the run's real ledger. The wall time of that process, including
interpreter start-up and imports, is one sample. Samples are banked in
``artifacts/hook/latency.json`` with provenance; the median is computed from them by
whatever reads the artifact, never typed by hand.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def time_stop_hook(ledger: Path, report: str, python: str = sys.executable) -> tuple[float, bool]:
    """Run the Stop hook once; return (seconds, whether it blocked)."""
    payload = json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": ledger.parent.name,
            "cwd": str(ledger.parent),
            "stop_hook_active": False,
            "last_assistant_message": report,
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        start = time.monotonic()
        proc = subprocess.run(
            [python, "-m", "receipts.hook", "stop", "--ledger", str(ledger), "--state", tmp],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.monotonic() - start
        errors = Path(tmp) / "errors.log"
        if proc.returncode != 0 or errors.is_file():
            detail = errors.read_text() if errors.is_file() else proc.stderr
            raise RuntimeError(f"stop hook failed on {ledger}: {detail[-500:]}")
    return elapsed, bool(proc.stdout.strip())


def main(argv: Sequence[str] | None = None) -> int:
    """Time the Stop hook on every recorded run; write the artifact."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("studies", nargs="+", type=Path, help="artifacts/studies/<study> dirs")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "hook" / "latency.json")
    args = parser.parse_args(argv)
    samples: list[float] = []
    rows = []
    for study in args.studies:
        for run_json in sorted((study / "runs").glob("*/run.json")):
            record = json.loads(run_json.read_text(encoding="utf-8"))
            if not str(record.get("report", "")).strip():
                continue
            for _ in range(args.repeats):
                seconds, blocked = time_stop_hook(
                    run_json.parent / "ledger.jsonl", record["report"]
                )
                samples.append(round(seconds, 4))
                rows.append(
                    {"run_id": record["run_id"], "seconds": round(seconds, 4), "blocked": blocked}
                )
    sha = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    out = {
        "schema": "receipts.hook.latency/1",
        "what": "wall time of one `python -m receipts.hook stop` process per recorded run",
        "samples_s": samples,
        "rows": rows,
        "provenance": {
            "git_sha": sha,
            "command": " ".join([sys.executable, *sys.argv]),
            "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpus": os.cpu_count(),
            },
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"hook latency: {len(samples)} samples written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
