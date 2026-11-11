"""Study plans: the arms, the study-level manipulation text, and every planned run.

A plan is written to ``artifacts/studies/<study>/plan.json`` and committed before any
of its runs (for confirmatory studies, with the preregistration that cites it). Runs
are executed in plan order, grouped by model so the local server restarts as rarely
as possible, and a run whose ``run.json`` already exists is never re-run.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from receipts.drivers.minimal_agent.loop import AgentConfig
from receipts.drivers.minimal_agent.protocol import ACTION_SCHEMA
from receipts.ledger.events import canonical_json, sha256_text
from receipts.study.spec import CONDITION_LEVELS, Arm, RunSpec, StudyText, check_conditions

#: minimal-agent sampling defaults for local arms (seed is set per run).
LOCAL_PARAMS: Mapping[str, Any] = {
    "temperature": 0.3,
    "max_tokens": 1024,
    "response_format": {"type": "json_object", "schema": dict(ACTION_SCHEMA)},
}
"""Request parameters of every local arm (DECISIONS D39, D46): the action grammar keeps
each reply a syntactically valid action, and 1024 tokens fits a typical file write."""


def local_arm(config_id: str, model: str, family: str, max_turns: int = 16) -> Arm:
    """A minimal-agent arm served by the local backend."""
    agent = AgentConfig(
        backend="local",
        model=model,
        max_turns=max_turns,
        params=dict(LOCAL_PARAMS),
        purpose=f"minimal-agent {model}",
    )
    return Arm(config_id=config_id, driver="minimal-agent", model=model, family=family, agent=agent)


@dataclass(frozen=True)
class Plan:
    """A study plan."""

    study: str
    arms: Sequence[Arm]
    runs: Sequence[RunSpec]
    text: StudyText = field(default_factory=StudyText)
    notes: str = ""

    def arm(self, config_id: str) -> Arm:
        """The arm with ``config_id``."""
        for arm in self.arms:
            if arm.config_id == config_id:
                return arm
        raise KeyError(config_id)

    def to_json(self) -> dict[str, Any]:
        """The plan as stored in ``plan.json``."""
        return {
            "schema": "receipts.study-plan/1",
            "study": self.study,
            "notes": self.notes,
            "text": asdict(self.text),
            "arms": [_arm_json(a) for a in self.arms],
            "runs": [{**asdict(r), "conditions": dict(r.conditions)} for r in self.runs],
        }

    def sha256(self) -> str:
        """Content hash of the plan (cited by preregistrations and run provenance)."""
        return sha256_text(canonical_json(self.to_json()))

    def ordered(self) -> list[RunSpec]:
        """Runs grouped by model (in first-appearance order), plan order within a model."""
        order: dict[str, int] = {}
        for run in self.runs:
            order.setdefault(self.arm(run.config_id).model, len(order))
        return sorted(
            self.runs,
            key=lambda r: (order[self.arm(r.config_id).model], self.runs.index(r)),
        )


def _arm_json(arm: Arm) -> dict[str, Any]:
    agent = asdict(arm.agent)
    agent["truncation"]["tools"] = sorted(arm.agent.truncation.tools)
    agent["flaky_tools"] = sorted(arm.agent.flaky_tools)
    return {
        "config_id": arm.config_id,
        "driver": arm.driver,
        "model": arm.model,
        "family": arm.family,
        "agent": agent,
    }


def _arm_from_json(data: Mapping[str, Any]) -> Arm:
    agent = dict(data["agent"])
    trunc = agent.pop("truncation")
    from receipts.drivers.minimal_agent.boundary import TruncationPolicy

    agent["truncation"] = TruncationPolicy(
        max_lines=trunc.get("max_lines"), tools=frozenset(trunc.get("tools", ()))
    )
    if "flaky_tools" in agent:
        agent["flaky_tools"] = frozenset(agent["flaky_tools"])
    return Arm(
        config_id=str(data["config_id"]),
        driver=str(data["driver"]),
        model=str(data["model"]),
        family=str(data["family"]),
        agent=AgentConfig(**agent),
    )


def load_plan(path: Path) -> Plan:
    """Read ``plan.json``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = [
        RunSpec(
            run_id=str(r["run_id"]),
            study=str(r["study"]),
            task_id=str(r["task_id"]),
            config_id=str(r["config_id"]),
            conditions={str(k): str(v) for k, v in r["conditions"].items()},
            seed=int(r["seed"]),
            mitigation=str(r.get("mitigation", "none")),
        )
        for r in data["runs"]
    ]
    return Plan(
        study=str(data["study"]),
        arms=[_arm_from_json(a) for a in data["arms"]],
        runs=runs,
        text=StudyText(**data.get("text", {})),
        notes=str(data.get("notes", "")),
    )


def write_plan(path: Path, plan: Plan) -> None:
    """Write ``plan.json`` after validating every run's arm and conditions."""
    ids = {a.config_id for a in plan.arms}
    seen: set[str] = set()
    for run in plan.runs:
        if run.config_id not in ids:
            raise ValueError(f"run {run.run_id} names unknown arm {run.config_id}")
        if run.run_id in seen:
            raise ValueError(f"duplicate run id {run.run_id}")
        seen.add(run.run_id)
        check_conditions(run.conditions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def smoke_plan(study: str, task_ids: Iterable[str], arm: Arm, seed: int = 0) -> Plan:
    """One run per task for one arm, with no manipulation (G6 smoke runs)."""
    runs = [
        RunSpec(f"{study}-{task_id}-{arm.config_id}", study, task_id, arm.config_id, {}, seed)
        for task_id in task_ids
    ]
    return Plan(study=study, arms=[arm], runs=runs, notes="smoke runs: no manipulation")


def half_fraction_cells() -> list[dict[str, str]]:
    """The 16 cells of the 2^(5-1) design with defining relation I = M1 M2 M3 M4 M5.

    Resolution V: every main effect and two-way interaction is estimable, aliased only
    with three-way or higher interactions.
    """
    factors = list(CONDITION_LEVELS)
    cells = []
    for code in range(16):
        bits = [(code >> i) & 1 for i in range(4)]
        bits.append((sum(bits) + 1) % 2)  # makes the product of the +/-1 codes equal +1
        cells.append({f: CONDITION_LEVELS[f][b] for f, b in zip(factors, bits, strict=True)})
    return cells


def factorial_plan(
    study: str,
    task_ids: Sequence[str],
    arms: Sequence[Arm],
    replicates: int,
    seed: int,
    text: StudyText,
) -> Plan:
    """Every arm gets the same ``replicates`` x 16 runs: identical tasks, cells, seeds.

    Tasks are assigned to cells by a seeded shuffle that balances tasks across cells as
    evenly as possible; the resulting (task, cell, seed) list is shared by every arm, so
    agents are compared on identical work.
    """
    rng = random.Random(seed)
    cells = half_fraction_cells() * replicates
    tasks = [task_ids[i % len(task_ids)] for i in range(len(cells))]
    rng.shuffle(tasks)
    seeds = [rng.randrange(1, 2**31) for _ in cells]
    runs = []
    for arm in arms:
        for i, (task, cell, run_seed) in enumerate(zip(tasks, cells, seeds, strict=True)):
            run_id = f"{study}-{i:03d}-{arm.config_id}"
            runs.append(RunSpec(run_id, study, task, arm.config_id, dict(cell), run_seed))
    return Plan(study=study, arms=list(arms), runs=runs, text=text)
