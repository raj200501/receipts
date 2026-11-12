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

from receipts.client.server import LocalModel, LocalServer
from receipts.ledger.events import sha256_text
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
MODEL = "synthetic-model"
PINNED = 16384
PINNED_WINDOWS = {MODEL: PINNED}
WINDOW = plan.ServerRequirement(
    min_n_ctx_per_slot=32768, max_parallel_slots=1, pinned_n_ctx_per_slot=PINNED
)
REASON = "SYNTHETIC: the final-report request outgrew the server's window per slot"


def smoke() -> plan.Plan:
    """A SYNTHETIC smoke plan: one run per task for one arm."""
    return plan.smoke_plan("smoke", TASKS, plan.local_arm("ma-syn", MODEL, "fam"))


def text_sha256(p: plan.Plan) -> str:
    """SHA-256 of the bytes write_plan writes for ``p``."""
    return hashlib.sha256(plan.plan_text(p).encode("utf-8")).hexdigest()


def amended(p: plan.Plan | None = None, replaces: str = EXCLUDED, **changes: Any) -> plan.Plan:
    """``p`` (the SYNTHETIC smoke plan by default) amended in place of ``replaces``."""
    p = p or smoke()
    fields: dict[str, Any] = {"decision": "D71", "reason": REASON, "date": "2026-11-12"}
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
    plan.check_amendments(after, PINNED_WINDOWS)
    # Byte for byte, the plan file is the old one plus the run and the amendment record,
    # and the record keeps the pinned window it raises.
    data = json.loads(plan.plan_text(after))
    assert data.pop("amendments") == [record.to_json()]
    assert record.to_json()["server"] == {
        "min_n_ctx_per_slot": 32768,
        "max_parallel_slots": 1,
        "pinned_n_ctx_per_slot": PINNED,
    }
    assert data["runs"].pop() == {**dataclasses.asdict(after.runs[-1]), "conditions": {}}
    assert json.dumps(data, indent=2, sort_keys=True) + "\n" == plan.plan_text(before)
    # It survives a round trip through plan.json.
    path = tmp_path / "plan.json"
    plan.write_plan(path, after)
    loaded = plan.load_plan(path)
    assert loaded.amendments == (record,) and loaded.to_json() == after.to_json()
    assert loaded.runs[-1] == after.runs[-1]


def test_the_plan_before_an_amendment_is_the_plan_it_amended() -> None:
    before = smoke()
    once = amended(before)
    twice = amended(once, replaces="smoke-ts-gamma-ma-syn")
    assert plan.plan_text(plan.plan_before(once)) == plan.plan_text(before)
    assert plan.plan_text(plan.plan_before(twice, 1)) == plan.plan_text(once)
    assert plan.plan_text(plan.plan_before(twice)) == plan.plan_text(before)
    assert [a.plan_sha256_before for a in twice.amendments] == [
        text_sha256(before),
        text_sha256(once),
    ]
    plan.check_amendments(twice, PINNED_WINDOWS)


def test_the_added_run_is_named_after_the_excluded_run_and_the_window() -> None:
    assert plan.amendment_run_id(EXCLUDED, WINDOW) == ADDED
    odd = dataclasses.replace(WINDOW, min_n_ctx_per_slot=20000)
    assert plan.amendment_run_id(EXCLUDED, odd) == f"{EXCLUDED}-ctx20000"


def test_the_added_run_has_its_own_response_cache() -> None:
    assert plan.amendment_cache("smoke", ADDED) == f"runs/smoke/cache/{ADDED}"


def test_a_second_amendment_of_the_same_task_is_refused() -> None:
    once = amended()
    larger = dataclasses.replace(WINDOW, min_n_ctx_per_slot=65536)
    with pytest.raises(ValueError, match="already has an amendment"):
        amended(once)
    # Nor may the added run itself be replaced, with another window or the same one.
    with pytest.raises(ValueError, match="already has an amendment"):
        amended(once, replaces=ADDED, server=larger)
    # Another task may still get its own amendment.
    twice = amended(once, replaces="smoke-ts-gamma-ma-syn")
    assert twice.replaced() == {EXCLUDED, "smoke-ts-gamma-ma-syn"}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        pytest.param({"replaces": "smoke-py-delta-ma-syn"}, "not a planned run", id="unplanned"),
        pytest.param({"server": plan.ServerRequirement(0, 1, PINNED)}, "positive", id="no-window"),
        pytest.param(
            {"server": plan.ServerRequirement(32768, 0, PINNED)}, "positive", id="no-slot"
        ),
        pytest.param({"server": plan.ServerRequirement(True, 1, PINNED)}, "positive", id="bool"),
        pytest.param({"server": plan.ServerRequirement(32768, 1, 0)}, "positive", id="no-pinned"),
        pytest.param(
            {"server": dataclasses.replace(WINDOW, max_parallel_slots=2)}, "one slot", id="2-slots"
        ),
        pytest.param(
            {"server": dataclasses.replace(WINDOW, min_n_ctx_per_slot=PINNED)},
            "does not raise",
            id="pinned-window",
        ),
        pytest.param(
            {"server": dataclasses.replace(WINDOW, min_n_ctx_per_slot=8192)},
            "does not raise",
            id="smaller-window",
        ),
        pytest.param({"reason": "  "}, "reason", id="no-reason"),
        pytest.param({"decision": ""}, "D71", id="no-decision"),
        pytest.param({"decision": "D70"}, "D71", id="other-decision"),
        pytest.param({"date": "12 November"}, "date", id="bad-date"),
    ],
)
def test_a_malformed_amendment_is_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        amended(**changes)


def test_only_the_exploratory_smoke_study_is_amended() -> None:
    arm = plan.local_arm("ma-syn", MODEL, "fam")
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


def rerun(p: plan.Plan, run_id: str, **changes: Any) -> plan.Plan:
    """``p`` with the planned run ``run_id`` changed (a hand edit, not an amendment)."""
    runs = [dataclasses.replace(r, **changes) if r.run_id == run_id else r for r in p.runs]
    return dataclasses.replace(p, runs=runs)


def extra_run(p: plan.Plan, *, before_last: bool) -> plan.Plan:
    """``p`` with a run of task py-beta added outside any amendment."""
    run = dataclasses.replace(p.runs[1], run_id="smoke-py-beta-ma-syn-r2")
    runs = list(p.runs)
    runs.insert(len(runs) - 1 if before_last else len(runs), run)
    return dataclasses.replace(p, runs=runs)


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        pytest.param(lambda: broken(run_id="smoke-py-delta"), "not a planned run", id="unplanned"),
        pytest.param(lambda: broken(replaces=ADDED), "in place of itself", id="itself"),
        pytest.param(
            lambda: broken(replaces="smoke-py-alpha-ma-syn"), "not the planned run", id="other-task"
        ),
        pytest.param(
            lambda: rerun(amended(), ADDED, seed=9), "not the planned run", id="added-run-seed"
        ),
        pytest.param(
            lambda: rerun(rerun(amended(), ADDED, seed=7), EXCLUDED, seed=7),
            "changed outside its amendments",
            id="both-seeds",
        ),
        pytest.param(
            lambda: rerun(
                rerun(amended(), ADDED, mitigation="honesty"), EXCLUDED, mitigation="honesty"
            ),
            "changed outside its amendments",
            id="both-mitigations",
        ),
        pytest.param(
            lambda: dataclasses.replace(
                amended(), arms=[plan.local_arm("ma-syn", MODEL, "fam", max_turns=40)]
            ),
            "changed outside its amendments",
            id="arm-edited",
        ),
        pytest.param(
            lambda: extra_run(amended(), before_last=False), "last runs", id="run-appended"
        ),
        pytest.param(
            lambda: extra_run(amended(), before_last=True),
            "changed outside its amendments",
            id="run-inserted",
        ),
        pytest.param(
            lambda: dataclasses.replace(amended(), amendments=amended().amendments * 2),
            "more than once",
            id="twice",
        ),
        pytest.param(
            lambda: dataclasses.replace(amended(), study="e4"), "not amended", id="other-study"
        ),
        pytest.param(lambda: broken(decision="D72"), "D71", id="other-decision"),
        pytest.param(
            lambda: broken(server=dataclasses.replace(WINDOW, max_parallel_slots=4)),
            "one slot",
            id="four-slots",
        ),
        pytest.param(
            lambda: broken(server=plan.ServerRequirement(16384, 4, PINNED)),
            "does not raise",
            id="the-excluded-runs-server",
        ),
        pytest.param(
            lambda: broken(server=dataclasses.replace(WINDOW, pinned_n_ctx_per_slot=32768)),
            "does not raise",
            id="pinned-raised-too",
        ),
        pytest.param(lambda: broken(plan_sha256_before="f" * 63), "SHA-256", id="bad-before-hash"),
        pytest.param(
            lambda: broken(plan_sha256_before="0" * 64),
            "changed outside its amendments",
            id="other-before-hash",
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


def test_the_pinned_window_an_amendment_raises_is_the_models() -> None:
    p = amended()
    plan.check_amendments(p)  # without the pinned models, the record's window is not compared
    plan.check_amendments(p, PINNED_WINDOWS)
    with pytest.raises(ValueError, match="pinned window of 8192"):
        plan.check_amendments(p, {MODEL: 8192})
    with pytest.raises(ValueError, match="not a pinned local model"):
        plan.check_amendments(p, {})


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
                    "server": {**dataclasses.asdict(WINDOW), "min_n_ctx_per_slot": "x"},
                }
            ],
            id="window-not-a-number",
        ),
        pytest.param(
            [
                {
                    **dataclasses.asdict(amended().amendments[0]),
                    "server": {**dataclasses.asdict(WINDOW), "max_parallel_slots": 1.0},
                }
            ],
            id="slots-not-an-integer",
        ),
        pytest.param(
            [
                {
                    **dataclasses.asdict(amended().amendments[0]),
                    "server": {"min_n_ctx_per_slot": 32768, "max_parallel_slots": 1},
                }
            ],
            id="no-pinned-window",
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
        (32768, 0, ["positive window per slot and at least one slot"]),
        (32768, -1, ["positive window per slot and at least one slot"]),
        (0, 1, ["positive window per slot and at least one slot"]),
    ],
)
def test_a_server_requirement_names_what_a_server_lacks(
    window: int, slots: int, problems: list[str]
) -> None:
    found = WINDOW.problems(window, slots)
    assert len(found) == len(problems)
    assert all(want in got for want, got in zip(problems, found, strict=True))
    assert WINDOW.describe() == (
        "at least 32768 tokens per slot (the pinned window is 16384) on at most 1 slot(s)"
    )


# A banked run record against its plan (DECISIONS D71) -------------------------------------

MODEL_PATH = Path("/nonexistent/synthetic.gguf")


def model_server(n_ctx: int = 32768, slots: int = 1, engine: str = "llama.cpp") -> dict[str, Any]:
    """A SYNTHETIC run record's model server, as tools/run_study.py records it: the
    server's own provenance, the pinned window and whether it was served, and what the
    live server reported it serves (nothing is served here)."""
    model = LocalModel(MODEL, "fam", MODEL_PATH, "0" * 64, "SYN", n_ctx)
    served = LocalServer(model, engine=engine, parallel=slots)
    record: dict[str, Any] = dict(served.provenance())
    record["n_ctx_per_slot_default"] = PINNED
    record["n_ctx_per_slot_is_default"] = n_ctx == PINNED
    if engine == "llama.cpp":
        record["reported"] = {
            "source": "GET /props",
            "n_ctx_per_slot": n_ctx,
            "total_slots": slots,
            "model_path": str(MODEL_PATH),
        }
    return record


def run_record(p: plan.Plan, run_id: str, **provenance: Any) -> dict[str, Any]:
    """A SYNTHETIC run.json of planned run ``run_id``, made as planned."""
    spec = next(run for run in p.runs if run.run_id == run_id)
    prov: dict[str, Any] = {
        "run_spec": {**dataclasses.asdict(spec), "conditions": dict(spec.conditions)},
        "model_server": model_server(PINNED, 4),
    }
    amendment = p.amendment(run_id)
    if amendment is not None:
        prov.update(
            plan_amendment=amendment.to_json(),
            model_server=model_server(),
            response_cache=plan.amendment_cache(p.study, run_id),
            git_sha="a" * 40,
            code="snapshot",
            snapshot_of="a" * 40,
            snapshot_verified=True,
            sandbox={"backend": "bwrap", "checkout_hidden": True, "shown_in_checkout": []},
        )
    prov.update(provenance)
    return {
        "run_id": run_id,
        "task_id": spec.task_id,
        "config_id": spec.config_id,
        "model": MODEL,
        "provenance": prov,
    }


def test_a_record_made_as_planned_has_no_problems() -> None:
    p = amended()
    assert plan.run_record_problems(p, run_record(p, "smoke-py-alpha-ma-syn")) == []
    assert plan.run_record_problems(p, run_record(p, ADDED)) == []
    clean_tree = run_record(p, ADDED, code="working tree", uncommitted_at_start=[])
    assert plan.run_record_problems(p, clean_tree) == []
    assert plan.server_record_problems(WINDOW, model_server()) == []
    assert plan.server_record_problems(WINDOW, model_server(65536)) == []


def rehash(server: dict[str, Any]) -> dict[str, Any]:
    """``server`` with its command's SHA-256 recomputed (a consistent edit)."""
    return {**server, "server_command_sha256": sha256_text(" ".join(server["server_command"]))}


def edit_flag(server: dict[str, Any], flag: str, value: str) -> dict[str, Any]:
    """``server`` with one flag of its command set to ``value``."""
    command = list(server["server_command"])
    command[command.index(flag) + 1] = value
    return {**server, "server_command": command}


def reports(server: dict[str, Any], **report: Any) -> dict[str, Any]:
    """``server`` with what the live server reported changed."""
    return {**server, "reported": {**server["reported"], **report}}


@pytest.mark.parametrize(
    ("server", "problem"),
    [
        pytest.param(model_server(PINNED, 4), "at least 32768 tokens per slot", id="pinned"),
        pytest.param(model_server(32768, 4), "at most 1 slot(s)", id="four-slots"),
        pytest.param({**model_server(PINNED), "n_ctx_per_slot": 32768}, "--ctx-size", id="window"),
        pytest.param(
            {**model_server(PINNED), "n_ctx_per_slot": 32768, "ctx_size": 32768},
            "--ctx-size",
            id="window-and-size",
        ),
        pytest.param(edit_flag(model_server(), "--port", "9999"), "SHA-256", id="command"),
        pytest.param(
            rehash(edit_flag(model_server(), "--parallel", "2")), "--parallel", id="slots-flag"
        ),
        pytest.param({**model_server(), "ctx_size": 65536}, "ctx_size", id="ctx-size"),
        pytest.param(
            {**model_server(), "n_ctx_per_slot_is_default": True}, "is_default", id="flag"
        ),
        pytest.param(
            {**model_server(), "n_ctx_per_slot_default": None}, "pinned window", id="no-default"
        ),
        pytest.param(
            {**model_server(), "n_ctx_per_slot_default": 8192}, "pinned window", id="other-default"
        ),
        pytest.param(
            {k: v for k, v in model_server().items() if k != "n_ctx_per_slot"},
            "window per slot",
            id="no-window",
        ),
        pytest.param({**model_server(), "parallel_slots": True}, "window per slot", id="bool"),
        pytest.param({**model_server(), "engine": "synthetic-engine"}, "llama.cpp", id="engine"),
        pytest.param(model_server(engine="llama-cpp-python"), "llama.cpp", id="python-engine"),
        pytest.param({**model_server(), "reported": None}, "reported", id="not-reported"),
        pytest.param(reports(model_server(), n_ctx_per_slot=16384), "reports", id="reports-16k"),
        pytest.param(reports(model_server(), total_slots=4), "reports", id="reports-4-slots"),
        pytest.param(
            reports(model_server(), model_path="/other/model.gguf"), "reports", id="reports-file"
        ),
        pytest.param("SYNTHETIC", "model server", id="not-an-object"),
    ],
)
def test_a_server_record_that_does_not_meet_or_match_itself_is_found(
    server: Any, problem: str
) -> None:
    found = plan.server_record_problems(WINDOW, server)
    assert any(problem in line for line in found), found


@pytest.mark.parametrize(
    ("run_id", "changes", "problem"),
    [
        pytest.param("smoke-py-delta-ma-syn", {}, "not a planned run", id="unplanned"),
        pytest.param(EXCLUDED, {}, "replaced", id="excluded-run-banked"),
        pytest.param("smoke-py-alpha-ma-syn", {"task_id": "py-beta"}, "task", id="other-task"),
        pytest.param("smoke-py-alpha-ma-syn", {"config_id": "ma-x"}, "arm", id="other-arm"),
        pytest.param("smoke-py-alpha-ma-syn", {"model": "other-model"}, "model", id="other-model"),
        pytest.param(ADDED, {"model": "other-model"}, "model", id="added-other-model"),
        pytest.param("smoke-py-alpha-ma-syn", {"seed": 5}, "run spec", id="other-seed"),
        pytest.param(ADDED, {"plan_amendment": None}, "plan amendment", id="no-amendment"),
        pytest.param(
            ADDED, {"model_server": model_server(PINNED, 4)}, "at least 32768", id="small-window"
        ),
        pytest.param(ADDED, {"response_cache": "runs/cache"}, "response cache", id="shared-cache"),
        pytest.param(ADDED, {"response_cache": None}, "response cache", id="no-cache"),
        pytest.param(ADDED, {"snapshot_verified": False}, "code that ran", id="unverified"),
        pytest.param(ADDED, {"snapshot_of": "b" * 40}, "code that ran", id="other-snapshot"),
        pytest.param(
            ADDED,
            {"code": "working tree", "uncommitted_at_start": ["src/x.py"]},
            "code that ran",
            id="dirty-tree",
        ),
        pytest.param(ADDED, {"sandbox": None}, "hid the checkout", id="no-sandbox"),
        pytest.param(
            ADDED,
            {"sandbox": {"backend": "bwrap", "checkout_hidden": False}},
            "hid the checkout",
            id="exposed-sandbox",
        ),
        pytest.param(ADDED, {"provenance": None}, "provenance", id="no-provenance"),
    ],
)
def test_a_record_not_made_as_planned_is_found(
    run_id: str, changes: dict[str, Any], problem: str
) -> None:
    p = amended()
    if run_id in {run.run_id for run in p.runs}:
        record = run_record(p, run_id)
    else:
        record = {"run_id": run_id, "task_id": "py-delta", "config_id": "ma-syn", "provenance": {}}
    for key in ("task_id", "config_id", "model", "provenance"):
        if key in changes:
            record[key] = changes.pop(key)
    if "seed" in changes:
        record["provenance"]["run_spec"]["seed"] = changes.pop("seed")
    record["provenance"] = record["provenance"] and {**record["provenance"], **changes}
    found = plan.run_record_problems(p, record)
    assert any(problem in line for line in found), found
