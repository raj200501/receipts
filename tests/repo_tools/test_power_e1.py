"""tools/power_e1.py: the prereg 0001 section 8 rule, on synthetic pilot records.

Every record built here is a synthetic test fixture, never model output.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import power_e1

EASY = dict(power_e1.FIRST_LEVELS)
HARD = {"M1": "unattainable", "M2": "truncated", "M3": "pressure", "M4": "long", "M5": "flaky"}
ARMS = ("ma-qwen7b", "ma-qwen1.5b", "ma-granite8b", "ma-granite2b")


def record(
    arm: str,
    task: str,
    cell: dict[str, str],
    *,
    false_success: bool,
    report: str = "Done.",
    wall_s: float = 600.0,
) -> dict[str, Any]:
    """One synthetic pilot run record with the fields the tool reads."""
    return {
        "run_id": f"pilot-{task}-{arm}-{'easy' if cell == EASY else 'hard'}",
        "task_id": task,
        "config_id": arm,
        "conditions": dict(cell),
        "report": report,
        "false_success": false_success,
        "wall_s": wall_s,
    }


def pilot(events_easy: int = 4) -> list[dict[str, Any]]:
    """Thirty-two synthetic records shaped like the pilot plan (4 tasks, 4 arms, 2 cells)."""
    out = []
    for t, task in enumerate(("py-a", "py-b", "ts-a", "ts-b")):
        for a, arm in enumerate(ARMS):
            out.append(record(arm, task, EASY, false_success=(t * 4 + a) < events_easy))
            out.append(record(arm, task, HARD, false_success=(t + a) % 2 == 0))
    return out


def test_base_rate_pools_reported_easy_runs_and_clips() -> None:
    records = pilot(events_easy=4)
    records.append(record("ma-qwen7b", "py-a", EASY, false_success=True, report="  "))
    rate = power_e1.base_rate(records)
    assert (rate["events"], rate["n"]) == (4, 16)
    assert rate["used"] == pytest.approx(0.25)
    assert power_e1.base_rate(pilot(events_easy=0))["used"] == power_e1.RATE_CLIP[0]
    assert power_e1.base_rate(pilot(events_easy=16))["used"] == power_e1.RATE_CLIP[1]
    assert power_e1.base_rate([])["used"] == 0.5


def test_random_sd_is_clipped_or_defaulted() -> None:
    sd = power_e1.random_sd(pilot())
    lo, hi = power_e1.SD_CLIP
    assert lo <= sd["used"] <= hi
    assert sd["n"] == 32
    one_task = [r for r in pilot() if r["task_id"] == "py-a"]
    failed = power_e1.random_sd(one_task)
    assert failed["used"] == power_e1.SD_DEFAULT
    assert failed["status"].startswith("fit failed")


def test_budget_sets_the_candidates() -> None:
    walls = dict.fromkeys(ARMS, 225.0)
    # 4 arms x 16 R runs x 225 s / 4 slots = R hours.
    assert power_e1.estimated_hours(4, walls) == pytest.approx(4.0)
    assert power_e1.candidates(walls, 6.5) == [4, 5, 6]
    assert power_e1.candidates(walls, 2.0) == [4]


def test_size_search_checks_the_five_manipulations_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The four arms enter the simulated design with no effect; their power stays near
    # alpha, so the rule must check the manipulations only, and says so explicitly.
    seen: dict[str, Any] = {}
    real = power_e1.smallest_sufficient

    def capture(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(power_e1, "smallest_sufficient", capture)
    search = power_e1.size_search(0.3, 1.0, 24, list(ARMS), [4], n_sim=2)
    assert seen["check"] == list(power_e1.FACTORS)
    assert seen["arm_effects"] == {arm: 0.0 for arm in ARMS if arm != power_e1.REFERENCE_ARM}
    assert search["check"] == list(power_e1.FACTORS)


def test_e1_arms_are_the_plan_arms() -> None:
    import make_plans

    assert power_e1.E1_ARMS == tuple(arm.config_id for arm in make_plans.ARMS) == ARMS
    assert power_e1.REFERENCE_ARM in power_e1.E1_ARMS


def test_choose_takes_the_smallest_sufficient_else_the_largest_affordable() -> None:
    assert power_e1.choose({"chosen": 5}, [4, 5, 6])[0] == 5
    r, how = power_e1.choose({"chosen": None}, [4, 5, 6])
    assert r == 6
    assert "largest affordable" in how


def test_main_writes_a_synthetic_planning_artifact(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for rec in pilot():
        d = runs / rec["run_id"]
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    out = tmp_path / "power.json"
    code = power_e1.main(
        [
            "--pilot",
            str(runs),
            "--out",
            str(out),
            "--n-sim",
            "20",
            "--n-tasks",
            "24",
            "--budget-hours",
            "5",
        ]
    )
    assert code == 0
    art = json.loads(out.read_text(encoding="utf-8"))
    assert art["synthetic"] is True
    assert art["replicates"] in (4, 5)
    assert art["planned_runs_per_config"] == 16 * art["replicates"]
    assert set(art["achieved_power"]) == set(power_e1.FACTORS)
    assert all(0.0 <= p <= 1.0 for p in art["achieved_power"].values())
    assert art["inputs"]["alpha"] == power_e1.ALPHA
    assert math.isclose(
        art["search"]["results"][0]["effects"][0]["log_odds"], math.log(power_e1.ODDS_RATIO)
    )
    assert len(art["provenance"]["inputs"]) == 32


def bank_pilot(runs: Path, records: list[dict[str, Any]]) -> None:
    """Write SYNTHETIC pilot records as banked runs under ``runs``."""
    for i, rec in enumerate(records):
        d = runs / f"{i:02d}-{rec.get('run_id', 'run')}"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")


def drop_arm(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pilot without the ma-granite2b arm (for example, every run of it failed)."""
    return [r for r in records if r["config_id"] != "ma-granite2b"]


def extra_arm(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pilot plus runs of an arm that E1 does not have."""
    return [*records, record("ma-other7b", "py-a", EASY, false_success=False)]


def no_arm(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pilot with one record that names no arm."""
    broken = dict(records[0])
    del broken["config_id"]
    return [broken, *records[1:]]


@pytest.mark.parametrize("change", [drop_arm, extra_arm, no_arm])
def test_main_refuses_unless_the_pilot_ran_exactly_the_four_e1_arms(
    tmp_path: Path,
    change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    bank_pilot(tmp_path / "runs", change(pilot()))
    out = tmp_path / "power.json"
    code = power_e1.main(["--pilot", str(tmp_path / "runs"), "--out", str(out), "--n-sim", "2"])
    assert code == 2
    assert not out.exists()
    assert "four E1 arms" in capsys.readouterr().err


def test_main_refuses_synthetic_or_missing_pilot(tmp_path: Path) -> None:
    out = tmp_path / "power.json"
    assert power_e1.main(["--pilot", str(tmp_path / "none"), "--out", str(out)]) == 2
    d = tmp_path / "runs" / "x"
    d.mkdir(parents=True)
    rec = record("ma-qwen7b", "py-a", EASY, false_success=False)
    rec["synthetic"] = True
    (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
    assert power_e1.main(["--pilot", str(tmp_path / "runs"), "--out", str(out)]) == 2
    assert not out.exists()
