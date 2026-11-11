"""Tests for study plans and the half-fraction factorial design."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from receipts.study import plan
from receipts.study.spec import CONDITION_LEVELS, RunSpec, StudyText


def code(cell: dict[str, str], factor: str) -> int:
    return 1 if cell[factor] == CONDITION_LEVELS[factor][1] else -1


def test_half_fraction_is_resolution_v() -> None:
    cells = plan.half_fraction_cells()
    assert len(cells) == 16 and len({tuple(sorted(c.items())) for c in cells}) == 16
    factors = list(CONDITION_LEVELS)
    for cell in cells:
        product = 1
        for f in factors:
            product *= code(cell, f)
        assert product == 1  # defining relation I = M1 M2 M3 M4 M5
    for f in factors:  # balanced main effects
        assert sum(code(c, f) for c in cells) == 0
    for a, b in itertools.combinations(factors, 2):  # orthogonal two-way interactions
        assert sum(code(c, a) * code(c, b) for c in cells) == 0
    for a, b, c in itertools.combinations(factors, 3):  # main effects never alias 2fi
        assert sum(code(x, a) * code(x, b) * code(x, c) for x in cells) == 0


def test_factorial_plan_shares_work_across_arms(tmp_path: Path) -> None:
    arms = [plan.local_arm("a1", "m1", "fam1"), plan.local_arm("a2", "m2", "fam2")]
    p = plan.factorial_plan(
        "e1",
        ["t1", "t2", "t3"],
        arms,
        replicates=2,
        seed=7,
        text=StudyText(pressure_suffix="Ship it.", flaky_rate=0.2),
    )
    assert len(p.runs) == 64
    by_arm = {a.config_id: [r for r in p.runs if r.config_id == a.config_id] for a in arms}
    work = [
        [(r.task_id, tuple(sorted(r.conditions.items())), r.seed) for r in runs]
        for runs in by_arm.values()
    ]
    assert work[0] == work[1]
    counts = {t: sum(1 for r in by_arm["a1"] if r.task_id == t) for t in ("t1", "t2", "t3")}
    assert max(counts.values()) - min(counts.values()) <= 1
    same = plan.factorial_plan("e1", ["t1", "t2", "t3"], arms, 2, 7, StudyText())
    assert [r.seed for r in same.runs] == [r.seed for r in p.runs]
    assert [r.config_id for r in p.ordered()][:32] == ["a1"] * 32
    path = tmp_path / "plan.json"
    plan.write_plan(path, p)
    loaded = plan.load_plan(path)
    assert loaded.to_json() == p.to_json() and loaded.sha256() == p.sha256()
    assert loaded.arm("a2").agent.model == "m2"
    with pytest.raises(KeyError):
        loaded.arm("zz")


def test_write_plan_validates(tmp_path: Path) -> None:
    arm = plan.local_arm("a1", "m1", "fam1")
    bad_arm = plan.Plan("s", [arm], [RunSpec("r", "s", "t", "nope", {}, 0)])
    with pytest.raises(ValueError, match="unknown arm"):
        plan.write_plan(tmp_path / "p.json", bad_arm)
    dup = plan.Plan("s", [arm], [RunSpec("r", "s", "t", "a1", {}, 0)] * 2)
    with pytest.raises(ValueError, match="duplicate"):
        plan.write_plan(tmp_path / "p.json", dup)
    bad_level = plan.Plan("s", [arm], [RunSpec("r", "s", "t", "a1", {"M1": "x"}, 0)])
    with pytest.raises(ValueError, match="unknown condition"):
        plan.write_plan(tmp_path / "p.json", bad_level)


def test_smoke_plan() -> None:
    arm = plan.local_arm("a1", "m1", "fam1", max_turns=12)
    p = plan.smoke_plan("smoke", ["t1", "t2"], arm)
    assert [r.run_id for r in p.runs] == ["smoke-t1-a1", "smoke-t2-a1"]
    assert all(r.conditions == {} for r in p.runs) and arm.agent.max_turns == 12
