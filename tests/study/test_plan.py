"""Tests for study plans, the half-fraction factorial design, and plan amendments.

Every plan, task id, model name, run, and reason here is a SYNTHETIC test fixture; no
model is called and nothing is a study result.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

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


# Plan amendments: one run in place of an excluded one (DECISIONS D71) ---------------------

TASKS = ("py-alpha", "py-beta", "ts-gamma")
EXCLUDED = "smoke-py-beta-ma-syn"
ADDED = "smoke-py-beta-ma-syn-ctx32k"
WINDOW = plan.ServerRequirement(min_n_ctx_per_slot=32768, max_parallel_slots=1)
REASON = "SYNTHETIC: the request outgrew the server's window per slot"


def smoke() -> plan.Plan:
    """A SYNTHETIC smoke plan: one run per task for one arm."""
    return plan.smoke_plan("smoke", TASKS, plan.local_arm("ma-syn", "synthetic-model", "fam"))


def text_sha256(p: plan.Plan) -> str:
    """SHA-256 of the bytes write_plan writes for ``p``."""
    return hashlib.sha256(plan.plan_text(p).encode("utf-8")).hexdigest()


def amended(p: plan.Plan | None = None, replaces: str = EXCLUDED, **changes: Any) -> plan.Plan:
    """``p`` (the SYNTHETIC smoke plan by default) amended in place of ``replaces``."""
    p = p or smoke()
    fields: dict[str, Any] = {
        "decision": "D71",
        "reason": REASON,
        "date": "2026-11-12",
        "plan_sha256_before": text_sha256(p),
    }
    fields.update(changes)
    server = fields.pop("server", WINDOW)
    return plan.amend_plan(p, replaces, server, **fields)


def test_a_plan_without_amendments_is_written_as_before(tmp_path: Path) -> None:
    p = smoke()
    assert p.amendments == () and "amendments" not in p.to_json()
    path = tmp_path / "plan.json"
    plan.write_plan(path, p)
    assert path.read_text(encoding="utf-8") == plan.plan_text(p)
    assert (
        path.read_text(encoding="utf-8") == json.dumps(p.to_json(), indent=2, sort_keys=True) + "\n"
    )
    assert plan.load_plan(path).amendments == ()


def test_an_amendment_adds_one_run_in_place_of_an_excluded_run(tmp_path: Path) -> None:
    before = smoke()
    after = amended(before)
    # The added run is the excluded run's planned spec under a new id, after every run.
    assert list(after.runs[:-1]) == list(before.runs)
    assert after.runs[-1] == dataclasses.replace(before.runs[1], run_id=ADDED)
    assert (after.study, after.arms, after.text, after.notes) == (
        before.study,
        before.arms,
        before.text,
        before.notes,
    )
    (record,) = after.amendments
    assert record == plan.PlanAmendment(
        run_id=ADDED,
        replaces=EXCLUDED,
        server=WINDOW,
        decision="D71",
        reason=REASON,
        date="2026-11-12",
        plan_sha256_before=text_sha256(before),
    )
    assert after.amendment(ADDED) == record and after.amendment(EXCLUDED) is None
    assert after.replaced() == frozenset({EXCLUDED})
    # Byte for byte, the plan file is the old one plus the run and the amendment record.
    data = json.loads(plan.plan_text(after))
    assert data.pop("amendments") == [record.to_json()]
    assert data["runs"].pop() == {**dataclasses.asdict(after.runs[-1]), "conditions": {}}
    assert json.dumps(data, indent=2, sort_keys=True) + "\n" == plan.plan_text(before)
    assert hashlib.sha256(plan.plan_text(before).encode()).hexdigest() == record.plan_sha256_before
    # It survives a round trip through plan.json.
    path = tmp_path / "plan.json"
    plan.write_plan(path, after)
    loaded = plan.load_plan(path)
    assert loaded.amendments == (record,) and loaded.to_json() == after.to_json()
    assert loaded.runs[-1] == after.runs[-1]


def test_the_added_run_is_named_after_the_excluded_run_and_the_window() -> None:
    assert plan.amendment_run_id(EXCLUDED, WINDOW) == ADDED
    odd = plan.ServerRequirement(min_n_ctx_per_slot=20000)
    assert plan.amendment_run_id(EXCLUDED, odd) == f"{EXCLUDED}-ctx20000"


def test_a_second_amendment_of_the_same_task_is_refused() -> None:
    once = amended()
    larger = plan.ServerRequirement(min_n_ctx_per_slot=65536)
    with pytest.raises(ValueError, match="already has an amendment"):
        amended(once, plan_sha256_before=text_sha256(once))
    # Nor may the added run itself be replaced, with another window or the same one.
    with pytest.raises(ValueError, match="already has an amendment"):
        amended(once, replaces=ADDED, server=larger, plan_sha256_before=text_sha256(once))
    # Another task may still get its own amendment.
    twice = amended(once, replaces="smoke-ts-gamma-ma-syn", plan_sha256_before=text_sha256(once))
    assert twice.replaced() == {EXCLUDED, "smoke-ts-gamma-ma-syn"}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        pytest.param({"replaces": "smoke-py-delta-ma-syn"}, "not a planned run", id="unplanned"),
        pytest.param({"server": plan.ServerRequirement(0)}, "positive", id="no-window"),
        pytest.param({"server": plan.ServerRequirement(32768, 0)}, "positive", id="no-slot"),
        pytest.param({"server": plan.ServerRequirement(True)}, "positive", id="bool-window"),
        pytest.param({"reason": "  "}, "reason", id="no-reason"),
        pytest.param({"decision": ""}, "decision", id="no-decision"),
        pytest.param({"date": "12 November"}, "date", id="bad-date"),
        pytest.param({"plan_sha256_before": "f" * 63}, "SHA-256", id="bad-before-hash"),
    ],
)
def test_a_malformed_amendment_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        amended(**changes)


def test_only_the_exploratory_smoke_study_is_amended() -> None:
    arm = plan.local_arm("ma-syn", "synthetic-model", "fam")
    e1 = plan.Plan("e1", [arm], [RunSpec("e1-000-ma-syn", "e1", "py-alpha", "ma-syn", {}, 3)])
    with pytest.raises(ValueError, match="not amended"):
        amended(e1, replaces="e1-000-ma-syn")


def test_a_new_run_id_that_is_already_planned_is_refused() -> None:
    base = smoke()
    taken = dataclasses.replace(base.runs[0], run_id=ADDED)
    with pytest.raises(ValueError, match="already planned"):
        amended(dataclasses.replace(base, runs=[*base.runs, taken]))


def broken(**record: Any) -> plan.Plan:
    """The amended SYNTHETIC plan with its amendment record changed."""
    good = amended()
    (amendment,) = good.amendments
    return dataclasses.replace(good, amendments=[dataclasses.replace(amendment, **record)])


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        pytest.param(lambda: broken(run_id="smoke-py-delta"), "not a planned run", id="unplanned"),
        pytest.param(lambda: broken(replaces=ADDED), "in place of itself", id="itself"),
        pytest.param(
            lambda: broken(replaces="smoke-py-alpha-ma-syn"), "not the planned run", id="other-task"
        ),
        pytest.param(
            lambda: dataclasses.replace(
                amended(),
                runs=[*smoke().runs, dataclasses.replace(smoke().runs[1], run_id=ADDED, seed=9)],
            ),
            "not the planned run",
            id="other-seed",
        ),
        pytest.param(
            lambda: dataclasses.replace(amended(), amendments=amended().amendments * 2),
            "more than once",
            id="twice",
        ),
        pytest.param(
            lambda: dataclasses.replace(amended(), study="e4"), "not amended", id="other-study"
        ),
    ],
)
def test_write_plan_refuses_an_amendment_that_does_not_hold(
    tmp_path: Path, bad: Any, message: str
) -> None:
    path = tmp_path / "plan.json"
    with pytest.raises(ValueError, match=message):
        plan.write_plan(path, bad())
    assert not path.exists()


@pytest.mark.parametrize(
    "amendments",
    [
        pytest.param({"run_id": ADDED}, id="an-object"),
        pytest.param(5, id="a-number"),
        pytest.param([{"run_id": ADDED, "replaces": EXCLUDED}], id="missing-fields"),
        pytest.param(
            [
                {
                    **dataclasses.asdict(amended().amendments[0]),
                    "server": {"min_n_ctx_per_slot": "x"},
                }
            ],
            id="window-not-a-number",
        ),
        pytest.param(
            [
                {
                    **dataclasses.asdict(amended().amendments[0]),
                    "server": {"min_n_ctx_per_slot": 32768, "max_parallel_slots": 1.0},
                }
            ],
            id="slots-not-an-integer",
        ),
        pytest.param(
            [{**dataclasses.asdict(amended().amendments[0]), "reason": ["SYNTHETIC"]}],
            id="reason-not-text",
        ),
    ],
)
def test_load_plan_refuses_malformed_amendment_records(tmp_path: Path, amendments: Any) -> None:
    data = amended().to_json()
    data["amendments"] = amendments
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="amendment"):
        plan.load_plan(path)


@pytest.mark.parametrize(
    ("window", "slots", "problems"),
    [
        (32768, 1, []),
        (65536, 1, []),
        (16384, 1, ["at least 32768 tokens per slot, not 16384"]),
        (32768, 4, ["at most 1 slot(s), not 4"]),
        (32768, 2, ["at most 1 slot(s), not 2"]),
        (16384, 4, ["at least 32768 tokens per slot, not 16384", "at most 1 slot(s), not 4"]),
    ],
)
def test_a_server_requirement_names_what_a_server_lacks(
    window: int, slots: int, problems: list[str]
) -> None:
    found = WINDOW.problems(window, slots)
    assert len(found) == len(problems)
    assert all(want in got for want, got in zip(problems, found, strict=True))
    assert WINDOW.describe() == "at least 32768 tokens per slot on at most 1 slot(s)"
