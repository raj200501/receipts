"""Write study plans to ``artifacts/studies/<study>/plan.json``.

    python tools/make_plans.py pilot            # pilot-* tasks only, never confirmatory
    python tools/make_plans.py smoke            # one unmanipulated run per benchmark task (G6)
    python tools/make_plans.py e1 --replicates R
    python tools/make_plans.py e4 --per-cell N

The E1/E4 task split is a seeded, language-stratified shuffle of the benchmark's
non-pilot tasks, recorded in the E1 plan's notes; E4 reads it back from there so the two
plans always agree. Pilot seeds come from a different generator than study seeds
(prereg/0001-e1-main-study.md section 9).

After writing a plan the tool prints ``plan_sha256: <hex>``, the SHA-256 of the bytes of
the plan.json file (the digest a preregistration records, prereg 0001 section 3 and
prereg 0002 section 3), beside the canonical content hash ``Plan.sha256()``, and for E1
and E4 the planned runs per configuration or per cell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tomllib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from receipts.client.models import GRANITE_2B, GRANITE_8B, QWEN_CODER_1_5B, QWEN_CODER_7B
from receipts.study.plan import Plan, factorial_plan, local_arm, smoke_plan, write_plan
from receipts.study.spec import Arm, RunSpec, StudyText

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "bench" / "tasks"
STUDIES = ROOT / "artifacts" / "studies"

ARMS: tuple[Arm, ...] = (
    local_arm("ma-qwen7b", QWEN_CODER_7B.name, "qwen"),
    local_arm("ma-qwen1.5b", QWEN_CODER_1_5B.name, "qwen"),
    local_arm("ma-granite8b", GRANITE_8B.name, "granite"),
    local_arm("ma-granite2b", GRANITE_2B.name, "granite"),
)
E1_SEED, E4_SEED, SPLIT_SEED, PILOT_SEED = 20261104, 20261105, 20261106, 77
FLAKY_RATE = 0.2
HARD = {"M1": "unattainable", "M2": "truncated", "M3": "pressure", "M4": "long", "M5": "flaky"}
EASY = {"M1": "attainable", "M2": "full", "M3": "neutral", "M4": "short", "M5": "reliable"}


def task_languages() -> dict[str, str]:
    """Every benchmark task id with its language, from its task.toml."""
    out = {}
    for toml in sorted(TASKS.glob("*/task.toml")):
        with toml.open("rb") as handle:
            out[toml.parent.name] = str(tomllib.load(handle)["language"])
    return out


def study_text() -> StudyText:
    """Shared manipulation settings: the pressure text from the benchmark, the flaky rate."""
    pressure = (ROOT / "bench" / "prompts" / "pressure.txt").read_text(encoding="utf-8").strip()
    return StudyText(pressure_suffix=pressure, flaky_rate=FLAKY_RATE)


def split(languages: dict[str, str]) -> tuple[list[str], list[str]]:
    """E1 and E4 task ids: two thirds and one third of each language, seeded."""
    rng = random.Random(SPLIT_SEED)
    e1: list[str] = []
    e4: list[str] = []
    for lang in sorted(set(languages.values())):
        ids = sorted(t for t, lg in languages.items() if lg == lang and not t.startswith("pilot-"))
        rng.shuffle(ids)
        cut = round(len(ids) * 2 / 3)
        e1 += ids[:cut]
        e4 += ids[cut:]
    return sorted(e1), sorted(e4)


def pilot_plan() -> Plan:
    """Each pilot task, each arm, at the all-first and all-second condition levels."""
    rng = random.Random(PILOT_SEED)
    tasks = sorted(t for t in task_languages() if t.startswith("pilot-"))
    runs = []
    for task in tasks:
        for name, cell in (("easy", EASY), ("hard", HARD)):
            seed = rng.randrange(1, 2**31)
            for arm in ARMS:
                rid = f"pilot-{task.removeprefix('pilot-')}-{name}-{arm.config_id}"
                runs.append(RunSpec(rid, "pilot", task, arm.config_id, dict(cell), seed))
    return Plan("pilot", list(ARMS), runs, study_text(), notes="pilot: never confirmatory")


def e4_plan(per_cell: int, e4_tasks: Sequence[str]) -> Plan:
    """Identical (task, M1, seed) triples for every (arm, mitigation) cell, M1 paired in tasks.

    prereg/0002-e4-mitigation.md section 3: ``per_cell`` (N) is even, and the N triples
    come in N / 2 pairs. Pair j uses the (j mod n)-th of the n held-out tasks in sorted
    order and holds an attainable triple, then an unattainable one, so M1 is balanced
    within every task and the pair counts of any two tasks differ by at most one. Each
    triple has its own seed, drawn in triple order by ``random.Random(20261105)``. Run ids
    are ``e4-<triple index>-<config_id>-<mitigation>``.

    Raises:
        ValueError: ``per_cell`` is not a positive even number, or the task list is
            empty, repeats a task, or holds a pilot task.
    """
    if per_cell < 2 or per_cell % 2:
        raise ValueError(f"runs per cell must be a positive even number, got {per_cell}")
    tasks = sorted(e4_tasks)
    if not tasks:
        raise ValueError("the held-out task list must be non-empty")
    if len(set(tasks)) != len(tasks):
        raise ValueError("the held-out task list must not repeat a task")
    pilots = [task for task in tasks if task.startswith("pilot-")]
    if pilots:
        raise ValueError(f"held-out tasks are never pilot tasks: {', '.join(pilots)}")
    rng = random.Random(E4_SEED)
    base = {"M2": "full", "M3": "neutral", "M4": "short", "M5": "reliable"}
    triples = []
    for pair in range(per_cell // 2):
        task = tasks[pair % len(tasks)]
        for level in ("attainable", "unattainable"):
            triples.append((task, {**base, "M1": level}, rng.randrange(1, 2**31)))
    arms = [a for a in ARMS if a.config_id in ("ma-qwen7b", "ma-granite8b")]
    runs = []
    for arm in arms:
        for mitigation in ("none", "honesty", "evidence", "hook"):
            for i, (task, cell, seed) in enumerate(triples):
                rid = f"e4-{i:03d}-{arm.config_id}-{mitigation}"
                runs.append(RunSpec(rid, "e4", task, arm.config_id, cell, seed, mitigation))
    notes = json.dumps({"e4_tasks": tasks})
    return Plan("e4", arms, runs, study_text(), notes=notes)


def file_sha256(path: Path) -> str:
    """SHA-256 of the file's bytes: for plan.json, the digest a preregistration records."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runs_per_group(plan: Plan) -> str | None:
    """The prereg line for the plan's planned runs per arm (E1) or per cell (E4), if uniform."""
    if plan.study == "e1":
        name = "planned_runs_per_config"
        counts = Counter(run.config_id for run in plan.runs)
    elif plan.study == "e4":
        name = "planned_runs_per_cell"
        counts = Counter(f"{run.config_id}/{run.mitigation}" for run in plan.runs)
    else:
        return None
    sizes = set(counts.values())
    return f"{name}: {sizes.pop()}" if len(sizes) == 1 else None


def summary(plan: Plan, path: Path) -> list[str]:
    """What the tool prints after writing a plan: count, path, and both digests."""
    lines = [
        f"{plan.study}: {len(plan.runs)} runs written to {path}",
        f"plan_sha256: {file_sha256(path)}",
        "  (SHA-256 of the plan.json bytes: the digest a preregistration records)",
        f"canonical content hash, Plan.sha256(): {plan.sha256()} (not the recorded digest)",
    ]
    per_group = runs_per_group(plan)
    return [*lines, per_group] if per_group else lines


def main(argv: Sequence[str] | None = None) -> int:
    """Write one study's plan."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("study", choices=("pilot", "smoke", "e1", "e4"))
    parser.add_argument("--replicates", type=int, default=4)
    parser.add_argument(
        "--per-cell", type=int, default=24, help="E4 runs per cell (N): a positive even number"
    )
    args = parser.parse_args(argv)
    if args.study == "e4" and (args.per_cell < 2 or args.per_cell % 2):
        parser.error(
            f"--per-cell must be a positive even number (prereg 0002 section 3), "
            f"got {args.per_cell}"
        )
    if args.study == "pilot":
        plan = pilot_plan()
    elif args.study == "smoke":
        tasks = sorted(task_languages())
        plan = smoke_plan("smoke", tasks, ARMS[0])
    elif args.study == "e1":
        e1, e4 = split(task_languages())
        plan = factorial_plan("e1", e1, ARMS, args.replicates, E1_SEED, study_text())
        plan = Plan(
            plan.study,
            plan.arms,
            plan.runs,
            plan.text,
            notes=json.dumps({"e1_tasks": e1, "e4_tasks": e4}),
        )
    else:
        e1_path = STUDIES / "e1" / "plan.json"
        if not e1_path.is_file():
            print(f"no E1 plan at {e1_path}: write it first (make_plans.py e1)", file=sys.stderr)
            return 2
        e1_plan = json.loads(e1_path.read_text(encoding="utf-8"))
        e4_tasks = json.loads(e1_plan["notes"])["e4_tasks"]
        try:
            plan = e4_plan(args.per_cell, e4_tasks)
        except ValueError as exc:
            print(f"cannot plan E4 from the split in {e1_path}: {exc}", file=sys.stderr)
            return 2
        if args.per_cell % (2 * len(e4_tasks)):
            print(
                f"note: {args.per_cell} runs per cell is not a multiple of 2 x "
                f"{len(e4_tasks)} held-out tasks, so the tasks get unequal run counts "
                "(their pair counts differ by at most one)",
                file=sys.stderr,
            )
    path = STUDIES / plan.study / "plan.json"
    write_plan(path, plan)
    for line in summary(plan, path):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
