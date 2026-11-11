"""Add or check the receipts-bench canary string (rule 9; DECISIONS D52).

    python tools/bench_canary.py --check   # exit 1 if any task lacks it or leaks it
    python tools/bench_canary.py --write   # add it where it is missing

Each task's ``task.toml`` and its answer-key files carry the canary; the files an agent
sees never do (see :mod:`receipts.bench.canary`). Adding the canary changes the task tree
hashes, so ``tools/bench_validate.py`` must bank a fresh reference validation afterwards.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from receipts.bench.canary import add_canary, canary_problems

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "bench" / "tasks"


def task_dirs(tasks_dir: Path) -> list[Path]:
    """Every task directory (one holding a ``task.toml``), sorted."""
    if not tasks_dir.is_dir():
        return []
    return sorted(p for p in tasks_dir.iterdir() if (p / "task.toml").is_file())


def main(argv: Sequence[str] | None = None) -> int:
    """Check (default) or write the canary in every task under ``--tasks-dir``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks-dir", type=Path, default=TASKS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report problems (the default)")
    mode.add_argument("--write", action="store_true", help="add the canary where missing")
    args = parser.parse_args(argv)
    tasks = task_dirs(args.tasks_dir)
    if not tasks:
        print(f"no tasks under {args.tasks_dir}", file=sys.stderr)
        return 2
    if args.write:
        changed = sum(len(add_canary(task)) for task in tasks)
        print(f"canary added to {changed} file(s) in {len(tasks)} task(s)")
    problems = [f"{task.name}/{p}" for task in tasks for p in canary_problems(task)]
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"CANARY: {'FAIL' if problems else 'PASS'} ({len(tasks)} tasks)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
