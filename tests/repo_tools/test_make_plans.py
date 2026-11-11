"""tools/make_plans.py: the E4 plan's paired M1 layout and the printed plan digests.

The task ids in the e4_plan tests are SYNTHETIC; the main() tests read the real
benchmark task list (read only) and write plans under tmp_path only. No study runs and
nothing here is a study result.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import pytest

import make_plans
from receipts.study.plan import Plan, load_plan

#: SYNTHETIC held-out task ids, twelve like the real split, deliberately not sorted.
E4_TASKS = [f"{lang}-held-{k:02d}" for k in (5, 1, 3, 0, 4, 2) for lang in ("ts", "py")]
BASE = {"M2": "full", "M3": "neutral", "M4": "short", "M5": "reliable"}
CONFIGS = ("ma-qwen7b", "ma-granite8b")

Triple = tuple[str, str, int]


def cells(plan: Plan) -> dict[tuple[str, str], list[Triple]]:
    """The (task, M1, seed) list of each (configuration, mitigation) cell, in plan order."""
    out: dict[tuple[str, str], list[Triple]] = {}
    for run in plan.runs:
        assert dict(run.conditions) == {**BASE, "M1": run.conditions["M1"]}
        key = (run.config_id, run.mitigation)
        out.setdefault(key, []).append((run.task_id, run.conditions["M1"], run.seed))
    return out


def test_e4_plan_pairs_the_m1_levels_within_each_task() -> None:
    plan = make_plans.e4_plan(48, E4_TASKS)
    by_cell = cells(plan)
    assert set(by_cell) == {
        (c, m) for c in CONFIGS for m in ("none", "honesty", "evidence", "hook")
    }
    assert len(plan.runs) == 8 * 48
    first = by_cell[("ma-qwen7b", "none")]
    assert all(triples == first for triples in by_cell.values())
    # Pair j: the (j mod n)-th task in sorted order, an attainable then an unattainable
    # triple, each with its own seed drawn in triple order.
    ordered = sorted(E4_TASKS)
    for j in range(24):
        attainable, unattainable = first[2 * j], first[2 * j + 1]
        assert attainable[0] == unattainable[0] == ordered[j % 12]
        assert (attainable[1], unattainable[1]) == ("attainable", "unattainable")
    rng = random.Random(20261105)
    assert [seed for _, _, seed in first] == [rng.randrange(1, 2**31) for _ in range(48)]
    # M1 is balanced within every task (the old layout gave each task one level only).
    assert Counter((task, m1) for task, m1, _ in first) == {
        (task, m1): 2 for task in E4_TASKS for m1 in ("attainable", "unattainable")
    }


def test_e4_plan_keeps_the_run_id_form_and_the_e1_arm_configurations() -> None:
    plan = make_plans.e4_plan(24, E4_TASKS)
    assert [arm.config_id for arm in plan.arms] == list(CONFIGS)
    e1_arms = {arm.config_id: arm for arm in make_plans.ARMS}
    assert all(arm == e1_arms[arm.config_id] for arm in plan.arms)
    first = cells(plan)[("ma-qwen7b", "none")]
    for run in plan.runs:
        index = int(run.run_id.split("-")[1])
        assert run.run_id == f"e4-{index:03d}-{run.config_id}-{run.mitigation}"
        assert (run.task_id, run.conditions["M1"], run.seed) == first[index]
        assert run.study == "e4"
    assert len({run.run_id for run in plan.runs}) == len(plan.runs)
    assert json.loads(plan.notes) == {"e4_tasks": sorted(E4_TASKS)}


def test_e4_plan_uses_the_sorted_task_order_whatever_the_input_order() -> None:
    forward = make_plans.e4_plan(24, sorted(E4_TASKS))
    backward = make_plans.e4_plan(24, sorted(E4_TASKS, reverse=True))
    assert forward.to_json() == backward.to_json() == make_plans.e4_plan(24, E4_TASKS).to_json()


def test_e4_plan_with_n_not_a_multiple_of_twice_the_tasks() -> None:
    # 13 pairs over 12 tasks: one task gets two pairs, the others one; M1 stays paired.
    first = cells(make_plans.e4_plan(26, E4_TASKS))[("ma-qwen7b", "none")]
    pairs = Counter(task for task, m1, _ in first if m1 == "attainable")
    assert sorted(pairs.values()) == [1] * 11 + [2]
    assert pairs == Counter(task for task, m1, _ in first if m1 == "unattainable")


@pytest.mark.parametrize(
    ("per_cell", "tasks", "message"),
    [
        (25, E4_TASKS, "even"),
        (0, E4_TASKS, "even"),
        (-2, E4_TASKS, "even"),
        (24, [], "non-empty"),
        (24, [*E4_TASKS, E4_TASKS[0]], "repeat"),
        (24, [*E4_TASKS[:-1], "pilot-py-x"], "pilot"),
    ],
)
def test_e4_plan_refuses_bad_input(per_cell: int, tasks: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_plans.e4_plan(per_cell, tasks)


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_main_prints_the_file_digest_of_each_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(make_plans, "STUDIES", tmp_path)
    assert make_plans.main(["e1", "--replicates", "4"]) == 0
    e1_path = tmp_path / "e1" / "plan.json"
    out = capsys.readouterr().out
    digest = file_sha256(e1_path)
    canonical = load_plan(e1_path).sha256()
    assert digest != canonical  # the two digests differ; the prereg records the first
    lines = out.splitlines()
    assert f"plan_sha256: {digest}" in lines
    assert "planned_runs_per_config: 64" in lines
    assert canonical in out and str(e1_path) in out
    assert make_plans.main(["e4", "--per-cell", "24"]) == 0
    e4_path = tmp_path / "e4" / "plan.json"
    lines = capsys.readouterr().out.splitlines()
    assert f"plan_sha256: {file_sha256(e4_path)}" in lines
    assert "planned_runs_per_cell: 24" in lines
    e4 = load_plan(e4_path)
    assert json.loads(e4.notes)["e4_tasks"] == json.loads(load_plan(e1_path).notes)["e4_tasks"]
    assert len(e4.runs) == 8 * 24


def test_main_refuses_an_odd_e4_size_and_a_missing_e1_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(make_plans, "STUDIES", tmp_path)
    assert make_plans.main(["e4", "--per-cell", "24"]) == 2
    assert "e1" in capsys.readouterr().err
    assert make_plans.main(["e1", "--replicates", "4"]) == 0
    with pytest.raises(SystemExit) as stop:
        make_plans.main(["e4", "--per-cell", "25"])
    assert stop.value.code == 2
    assert "even" in capsys.readouterr().err
    assert not (tmp_path / "e4").exists()


def test_main_notes_when_the_tasks_get_unequal_run_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(make_plans, "STUDIES", tmp_path)
    assert make_plans.main(["e1", "--replicates", "4"]) == 0
    n_tasks = len(json.loads(load_plan(tmp_path / "e1" / "plan.json").notes)["e4_tasks"])
    capsys.readouterr()
    assert make_plans.main(["e4", "--per-cell", str(2 * n_tasks + 2)]) == 0
    assert "unequal" in capsys.readouterr().err
    assert make_plans.main(["e4", "--per-cell", str(2 * n_tasks)]) == 0
    assert "unequal" not in capsys.readouterr().err
