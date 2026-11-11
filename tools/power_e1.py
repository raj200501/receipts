"""E1 sample size (prereg/0001-e1-main-study.md section 8): the replicate count R.

    python tools/power_e1.py                 # writes artifacts/power/e1_power.json
    python tools/power_e1.py --n-sim 200 --out runs/power/try.json

Planning inputs come from the banked pilot (``artifacts/studies/pilot/runs/*/run.json``:
real runs of the ``pilot-*`` tasks, which are never pooled with confirmatory data):

- **Base rate.** Y1 (false success) among the pilot runs with a non-empty final report in
  the easy cell (every manipulation at its first level), pooled over the arms, clipped to
  ``[0.05, 0.95]`` so a pilot with no events (or only events) still gives a usable value.
- **Task random-effect SD.** The random-intercept SD of the Laplace GLMM of Y1 on every
  pilot run with a non-empty final report, with fixed effects for the arm and the cell
  (easy or hard) and clusters by task, clipped to ``[0.5, 2.0]``; 1.0 when the fit
  raises, does not converge, or is separated.
- **Run duration.** Per arm, the mean wall time of its pilot runs (the pilot runs four
  at a time on the shared CPU, as E1 does).

The tool refuses (exit 2) unless the pilot banked runs of exactly the four E1 arms
(``E1_ARMS``): an arm with no banked pilot run would drop out of both the wall-time
estimate and the simulated design, and a run of another arm would enter them.

Rule: the candidates are R = 4, 5, ... up to the largest R whose estimated E1 wall time,
the sum over arms of ``16 R mean_wall_s / PARALLEL`` seconds, fits the budget (default
20 hours). R is the smallest candidate at which every manipulation's simulated power
(``receipts.analysis.power.smallest_sufficient``) reaches 0.8 for an odds ratio of 2.0
at alpha 0.005 (the Holm-adjusted level of the first of ten tests), with the E1 design:
the 16-cell half fraction replicated R times over the E1 tasks, four arms with no arm
effect, 1000 simulated datasets, seed 20261104, Laplace fits. If no candidate reaches
0.8, R is the largest affordable candidate and its power is stated; if even R = 4 does
not fit the budget, R is 4 and the overrun is recorded. The artifact is a simulation on
synthetic data (``"synthetic": true``), a design input and never a study result.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from receipts.analysis import (
    Formula,
    build_design,
    fit_glmm,
    half_fraction,
    smallest_sufficient,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT_RUNS = ROOT / "artifacts" / "studies" / "pilot" / "runs"
OUT = ROOT / "artifacts" / "power" / "e1_power.json"

FACTORS = ("M1", "M2", "M3", "M4", "M5")
FIRST_LEVELS = {"M1": "attainable", "M2": "full", "M3": "neutral", "M4": "short", "M5": "reliable"}
E1_ARMS = ("ma-qwen7b", "ma-qwen1.5b", "ma-granite8b", "ma-granite2b")
"""The four E1 arms (prereg 0001 section 3, ``ARMS`` in tools/make_plans.py)."""
REFERENCE_ARM = "ma-qwen7b"
ODDS_RATIO = 2.0
ALPHA = 0.005
TARGET = 0.8
MIN_REPLICATES = 4
CELLS = 16
PARALLEL = 4
SEED = 20261104
RATE_CLIP = (0.05, 0.95)
SD_CLIP = (0.5, 2.0)
SD_DEFAULT = 1.0


def load_runs(runs_dir: Path) -> list[dict[str, Any]]:
    """Every banked run record under ``runs_dir`` (directories with ``run.json``), by id."""
    records = []
    for path in sorted(runs_dir.glob("*/run.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def arm_problem(records: Sequence[Mapping[str, Any]]) -> str | None:
    """Why the pilot records are not runs of exactly the four E1 arms (None when they are)."""
    rule = f"the pilot must have banked runs of exactly the four E1 arms ({', '.join(E1_ARMS)})"
    arms = [record.get("config_id") for record in records]
    if any(not isinstance(arm, str) or not arm for arm in arms):
        return f"{rule}: a record names no arm (config_id)"
    found = {str(arm) for arm in arms}
    missing = [arm for arm in E1_ARMS if arm not in found]
    unexpected = sorted(found - set(E1_ARMS))
    if not missing and not unexpected:
        return None
    parts = [f"missing {', '.join(missing)}"] if missing else []
    parts += [f"unexpected {', '.join(unexpected)}"] if unexpected else []
    return f"{rule}: {'; '.join(parts)}"


def _reported(record: Mapping[str, Any]) -> bool:
    return bool(str(record.get("report") or "").strip())


def _cell(record: Mapping[str, Any]) -> str:
    conditions = record.get("conditions") or {}
    return "easy" if all(conditions.get(f) == FIRST_LEVELS[f] for f in FACTORS) else "hard"


def _clip(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])


def base_rate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Y1 among reported easy-cell runs, pooled over arms, with the clipped value used."""
    easy = [r for r in records if _reported(r) and _cell(r) == "easy"]
    events = sum(bool(r.get("false_success")) for r in easy)
    raw = events / len(easy) if easy else None
    used = _clip(raw if raw is not None else 0.5, RATE_CLIP)
    return {"events": events, "n": len(easy), "raw": raw, "used": used, "clip": list(RATE_CLIP)}


def random_sd(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Task random-intercept SD of Y1 from the pilot (Laplace GLMM), clipped or defaulted."""
    rows = [
        {
            "y": bool(r.get("false_success")),
            "config_id": str(r["config_id"]),
            "cell": _cell(r),
            "task_id": str(r["task_id"]),
        }
        for r in records
        if _reported(r)
    ]
    out: dict[str, Any] = {"n": len(rows), "raw": None, "status": "", "clip": list(SD_CLIP)}
    try:
        formula = Formula(
            "y",
            ("config_id", "cell"),
            reference={"config_id": REFERENCE_ARM, "cell": "easy"},
            group="task_id",
        )
        fit = fit_glmm(build_design(rows, formula), n_agq=1)
    except ValueError as exc:
        out.update(status=f"fit failed: {exc}", used=SD_DEFAULT)
        return out
    out["raw"] = fit.random_sd
    if not fit.converged or fit.separation or fit.random_sd is None:
        reason = "separated" if fit.separation else "not converged"
        out.update(status=f"fit {reason}; default used", used=SD_DEFAULT)
        return out
    out.update(status="fit converged", used=_clip(float(fit.random_sd), SD_CLIP))
    return out


def mean_wall_s(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Mean wall time per arm, in seconds."""
    walls: dict[str, list[float]] = {}
    for r in records:
        walls.setdefault(str(r["config_id"]), []).append(float(r["wall_s"]))
    return {arm: sum(v) / len(v) for arm, v in sorted(walls.items())}


def estimated_hours(replicates: int, walls: Mapping[str, float]) -> float:
    """Estimated E1 wall time: every arm runs 16 R runs, PARALLEL at a time."""
    return sum(CELLS * replicates * w for w in walls.values()) / PARALLEL / 3600.0


def candidates(walls: Mapping[str, float], budget_hours: float) -> list[int]:
    """R = 4, 5, ... while the estimate fits the budget; [4] when even 4 does not."""
    out = [MIN_REPLICATES]
    while estimated_hours(out[-1] + 1, walls) <= budget_hours:
        out.append(out[-1] + 1)
    return out


def e1_task_count() -> int:
    """Number of E1 tasks in the seeded split that tools/make_plans.py uses."""
    sys.path.insert(0, str(ROOT / "tools"))
    import make_plans

    e1, _ = make_plans.split(make_plans.task_languages())
    return len(e1)


def size_search(
    rate: float,
    sd: float,
    n_tasks: int,
    arms: Sequence[str],
    replicates: Sequence[int],
    n_sim: int,
) -> dict[str, Any]:
    """The preregistered search over ``replicates`` (module docstring), as a dict.

    The rule checks the five manipulations only: the arms enter the design with no
    effect, so their power stays near alpha and is never a target.
    """
    effects = {f: math.log(ODDS_RATIO) for f in FACTORS}
    search = smallest_sufficient(
        "replicates",
        list(replicates),
        TARGET,
        check=list(FACTORS),
        base_rate=rate,
        effects=effects,
        random_sd=sd,
        n_tasks=n_tasks,
        alpha=ALPHA,
        n_sim=n_sim,
        seed=SEED,
        cells=half_fraction(FACTORS),
        arm_effects={arm: 0.0 for arm in arms if arm != REFERENCE_ARM},
        n_agq=1,
    )
    return search.as_dict()


def choose(search: Mapping[str, Any], replicates: Sequence[int]) -> tuple[int, str]:
    """R and how it was reached: the smallest sufficient, else the largest affordable."""
    if search["chosen"] is not None:
        return int(search["chosen"]), "smallest R with power >= 0.8 for every manipulation"
    return int(replicates[-1]), "no affordable R reached 0.8: largest affordable R"


def provenance(sources: Sequence[Path]) -> dict[str, Any]:
    """Git SHA, command, time, and the SHA-256 of every pilot record read."""
    sha = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "git_sha": sha,
        "command": " ".join([Path(sys.executable).name, *sys.argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "inputs": {
            str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sources
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Compute R from the banked pilot and write the power artifact."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", type=Path, default=PILOT_RUNS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--n-sim", type=int, default=1000)
    parser.add_argument("--budget-hours", type=float, default=20.0)
    parser.add_argument("--n-tasks", type=int, default=None, help="default: the E1 split")
    args = parser.parse_args(argv)
    records = load_runs(args.pilot)
    if not records:
        print(f"no banked pilot runs under {args.pilot}", file=sys.stderr)
        return 2
    if any(r.get("synthetic") for r in records):
        print("a pilot record is marked synthetic; refusing", file=sys.stderr)
        return 2
    problem = arm_problem(records)
    if problem is not None:
        print(f"{problem}; refusing", file=sys.stderr)
        return 2
    rate, sd, walls = base_rate(records), random_sd(records), mean_wall_s(records)
    n_tasks = args.n_tasks if args.n_tasks is not None else e1_task_count()
    replicates = candidates(walls, args.budget_hours)
    search = size_search(rate["used"], sd["used"], n_tasks, list(walls), replicates, args.n_sim)
    chosen, how = choose(search, replicates)
    evaluated = dict(zip(search["candidates"], search["results"], strict=True))
    final = evaluated[chosen]
    artifact = {
        "schema": "receipts.power.e1/1",
        "synthetic": True,
        "note": "Simulated power on synthetic data from pilot planning inputs: a design "
        "input for prereg/0001 section 8, never a study result.",
        "rule": __doc__.split("Rule: ", 1)[1].split("\n\n", 1)[0].replace("\n", " "),
        "inputs": {
            "pilot_runs": [str(r["run_id"]) for r in records],
            "base_rate": rate,
            "random_sd": sd,
            "mean_wall_s": walls,
            "n_tasks": n_tasks,
            "cells": CELLS,
            "parallel": PARALLEL,
            "budget_hours": args.budget_hours,
            "odds_ratio": ODDS_RATIO,
            "alpha": ALPHA,
            "target": TARGET,
            "n_sim": args.n_sim,
            "seed": SEED,
        },
        "estimated_hours": {str(r): round(estimated_hours(r, walls), 2) for r in replicates},
        "budget_overrun": estimated_hours(MIN_REPLICATES, walls) > args.budget_hours,
        "search": search,
        "replicates": chosen,
        "how": how,
        "planned_runs_per_config": CELLS * chosen,
        "achieved_power": {e["name"]: e["power"] for e in final["effects"] if e["name"] in FACTORS},
        "provenance": provenance(sorted(args.pilot.glob("*/run.json"))),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    low = min(artifact["achieved_power"].values())
    print(
        f"R = {chosen} ({how}); planned_runs_per_config = {CELLS * chosen}; "
        f"lowest manipulation power {low:.3f}; written to {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
