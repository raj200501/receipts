"""Tests for receipts.analysis.power.

Every dataset here is SIMULATED by the power code itself from stated design
parameters; nothing is agent data and no number here is a study result.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from numpy.polynomial.hermite_e import hermegauss
from scipy.special import expit, logit
from scipy.stats import norm

from receipts.analysis.power import (
    EffectPower,
    PowerResult,
    SampleSizeSearch,
    full_factorial,
    half_fraction,
    simulate_power,
    smallest_sufficient,
)
from receipts.study.plan import half_fraction_cells
from receipts.study.spec import CONDITION_LEVELS

FACTORS = ("M1", "M2", "M3", "M4", "M5")


# Design helpers ---------------------------------------------------------------------


def test_full_factorial_order() -> None:
    assert full_factorial(["A", "B"]) == (
        {"A": 0, "B": 0},
        {"A": 0, "B": 1},
        {"A": 1, "B": 0},
        {"A": 1, "B": 1},
    )
    assert len(full_factorial(FACTORS)) == 32


def test_half_fraction_matches_the_study_plan() -> None:
    cells = half_fraction(FACTORS)
    assert len(cells) == 16
    for cell in cells:
        assert math.prod(2 * v - 1 for v in cell.values()) == 1
    plan = {
        tuple(CONDITION_LEVELS[f].index(cell[f]) for f in FACTORS) for cell in half_fraction_cells()
    }
    assert {tuple(cell[f] for f in FACTORS) for cell in cells} == plan
    other = half_fraction(FACTORS, sign=-1)
    assert len(other) == 16 and not set(map(str, other)) & set(map(str, cells))


@pytest.mark.parametrize(
    ("factors", "sign", "message"),
    [
        (["A"], 1, "at least two"),
        (["A", "B"], 0, "sign"),
        (["A", "A"], 1, "unique"),
        (["A", ""], 1, "non-empty"),
    ],
)
def test_design_helpers_reject_bad_input(factors: list[str], sign: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        half_fraction(factors, sign=sign)


# Simulation ---------------------------------------------------------------------------


def test_power_is_reproducible_and_seeded() -> None:
    kwargs: dict[str, Any] = {
        "base_rate": 0.3,
        "effects": {"M1": 1.0},
        "random_sd": 0.5,
        "n_tasks": 8,
        "runs_per_task_per_cell": 3,
        "n_sim": 6,
    }
    first = simulate_power(**kwargs, seed=1)
    assert simulate_power(**kwargs, seed=1) == first
    assert simulate_power(**kwargs, seed=2) != first
    assert isinstance(first, PowerResult)
    assert (first.n_sim, first.n_obs, first.n_tasks, first.n_cells, first.n_arms) == (
        6,
        48,
        8,
        2,
        1,
    )
    assert first.layout == "crossed"


def test_null_effect_rejects_at_about_alpha() -> None:
    # 200 simulated datasets at alpha 0.1: about 20 rejections expected, SD about 4.2.
    result = simulate_power(
        base_rate=0.35,
        effects={"M1": 0.0},
        random_sd=0.6,
        n_tasks=16,
        runs_per_task_per_cell=3,
        alpha=0.1,
        n_sim=200,
        seed=7,
    )
    null = result.power_of("M1")
    assert result.n_failed == 0
    assert 8 <= null.rejections <= 34
    assert null.rejections_correct_sign == 0
    assert null.ci_low <= null.power <= null.ci_high


def normal_approximation_power(p0: float, effect: float, n_per_cell: int, alpha: float) -> float:
    """Two-sided Wald power for a log odds ratio between two independent groups."""
    p1 = float(expit(logit(p0) + effect))
    se = math.sqrt(1 / (n_per_cell * p0 * (1 - p0)) + 1 / (n_per_cell * p1 * (1 - p1)))
    crit = norm.ppf(1 - alpha / 2)
    return float(norm.cdf(abs(effect) / se - crit) + norm.cdf(-abs(effect) / se - crit))


def two_group_wald_power(p0: float, effect: float, n_per_cell: int, alpha: float) -> float:
    """Power of the 2x2 Wald test of the log odds ratio, from 100000 SYNTHETIC tables.

    With no task effect the logistic MLE in a two-cell design is the sample log odds
    ratio with Woolf's standard error, so this is the exact power of that test (up to
    Monte Carlo error of about 0.0013).
    """
    rng = np.random.default_rng(0)
    p1 = float(expit(logit(p0) + effect))
    x0 = rng.binomial(n_per_cell, p0, 100_000)
    x1 = rng.binomial(n_per_cell, p1, 100_000)
    ok = (x0 > 0) & (x0 < n_per_cell) & (x1 > 0) & (x1 < n_per_cell)
    x0, x1 = np.clip(x0, 1, n_per_cell - 1), np.clip(x1, 1, n_per_cell - 1)
    lor = np.log(x1 / (n_per_cell - x1)) - np.log(x0 / (n_per_cell - x0))
    se = np.sqrt(1 / x1 + 1 / (n_per_cell - x1) + 1 / x0 + 1 / (n_per_cell - x0))
    return float(np.mean(ok & (np.abs(lor / se) > norm.ppf(1 - alpha / 2))))


def test_power_matches_the_exact_wald_power_without_task_effects() -> None:
    exact = two_group_wald_power(0.3, 0.8, n_per_cell=100, alpha=0.05)
    assert exact == pytest.approx(
        normal_approximation_power(0.3, 0.8, n_per_cell=100, alpha=0.05), abs=0.03
    )
    result = simulate_power(
        base_rate=0.3,
        effects={"M1": 0.8},
        random_sd=0.0,
        n_tasks=10,
        runs_per_task_per_cell=10,
        n_sim=200,
        seed=3,
    )
    # 200 datasets: Monte Carlo SD of the power is about 0.029; 0.1 is about 3.4 SD.
    assert result.n_failed == 0
    assert result.power_of("M1").power == pytest.approx(exact, abs=0.1)


def test_large_effects_are_detected_with_the_right_sign() -> None:
    result = simulate_power(
        base_rate=0.4,
        effects={"M1": 2.5, "M2": -2.5},
        random_sd=0.5,
        n_tasks=12,
        runs_per_task_per_cell=2,
        n_sim=20,
        seed=11,
    )
    for name in ("M1", "M2"):
        effect = result.power_of(name)
        assert isinstance(effect, EffectPower)
        assert effect.power >= 0.9
        assert effect.rejections_correct_sign == effect.rejections
    assert result.power_of("M2").log_odds == -2.5


def test_power_grows_with_the_number_of_tasks() -> None:
    def power(n_tasks: int) -> float:
        result = simulate_power(
            base_rate=0.3,
            effects={"M1": 0.7},
            random_sd=0.8,
            n_tasks=n_tasks,
            runs_per_task_per_cell=2,
            n_sim=40,
            seed=5,
        )
        return result.power_of("M1").power

    assert power(40) > power(8) + 0.2


def test_simulated_outcome_rate_matches_the_model() -> None:
    base, effect, sd = 0.2, 1.1, 1.2
    result = simulate_power(
        base_rate=base,
        effects={"M1": effect},
        random_sd=sd,
        n_tasks=20,
        runs_per_task_per_cell=4,
        n_sim=30,
        seed=9,
    )
    nodes, weights = hermegauss(60)

    def marginal(eta: float) -> float:
        return float(np.sum(weights * expit(eta + sd * nodes)) / math.sqrt(2 * math.pi))

    expected = 0.5 * (marginal(logit(base)) + marginal(logit(base) + effect))
    assert result.mean_outcome_rate == pytest.approx(expected, abs=0.03)
    assert result.marginal_base_rate == pytest.approx(marginal(logit(base)), abs=1e-9)
    assert result.marginal_base_rate > base  # averaging over tasks pulls a low rate up


def test_replicated_layout_with_arms_mirrors_the_study_plan() -> None:
    result = simulate_power(
        base_rate=0.3,
        effects=dict.fromkeys(FACTORS, 0.5),
        random_sd=0.7,
        n_tasks=10,
        n_sim=3,
        seed=1,
        cells=half_fraction(FACTORS),
        replicates=2,
        arm_effects={"small": -0.4, "other": 0.2},
    )
    assert result.layout == "replicated"
    assert (result.n_obs, result.n_tasks, result.n_cells, result.n_arms) == (96, 10, 16, 3)
    names = [e.name for e in result.effects]
    assert names == [*FACTORS, "arm[T.small]", "arm[T.other]"]
    assert result.power_of("arm[T.small]").log_odds == -0.4
    few_tasks = simulate_power(
        base_rate=0.3,
        effects={"M1": 0.5, "M2": 0.5},
        random_sd=0.7,
        n_tasks=50,
        n_sim=2,
        replicates=3,
    )
    assert few_tasks.n_tasks == 12 and few_tasks.n_obs == 12  # 4 cells x 3 replicates


def test_failed_fits_count_as_non_rejections() -> None:
    # A rare outcome with little data: some datasets have no events at all.
    result = simulate_power(
        base_rate=0.02,
        effects={"M1": 1.0},
        random_sd=0.5,
        n_tasks=4,
        runs_per_task_per_cell=2,
        n_sim=30,
        seed=2,
    )
    assert result.n_failed > 0
    assert result.power_of("M1").rejections <= result.n_sim - result.n_failed


def test_power_result_lookup_and_dict() -> None:
    result = simulate_power(
        base_rate=0.3,
        effects={"M1": 0.5},
        random_sd=0.5,
        n_tasks=6,
        runs_per_task_per_cell=2,
        n_sim=3,
        seed=4,
        n_agq=3,
    )
    with pytest.raises(KeyError):
        result.power_of("M9")
    out = result.as_dict()
    assert out["effects"][0]["name"] == "M1"
    assert out["n_agq"] == 3 and out["seed"] == 4 and out["synthetic"] is True
    assert out["method"].startswith("simulation")
    assert out["effects"][0]["power"] == result.power_of("M1").power


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_rate": 0.0}, "base_rate"),
        ({"base_rate": 1.0}, "base_rate"),
        ({"effects": {}}, "at least one"),
        ({"effects": {"M1": math.nan}}, "finite"),
        ({"effects": {"": 1.0}}, "non-empty"),
        ({"random_sd": -0.1}, "random_sd"),
        ({"n_tasks": 1}, "n_tasks"),
        ({"runs_per_task_per_cell": 0}, "runs_per_task_per_cell"),
        ({"alpha": 1.0}, "alpha"),
        ({"n_sim": 0}, "n_sim"),
        ({"cells": [{"M1": 0}, {"M1": 2}]}, "0 or 1"),
        ({"cells": [{"M1": 0}, {"M2": 1}]}, "exactly"),
        ({"cells": [{"M1": 0}, {"M1": 0}]}, "rank deficient"),
        ({"replicates": 0}, "replicates"),
        ({"replicates": 2, "runs_per_task_per_cell": 2}, "either"),
        ({"arm_effects": {"M1": 0.1}}, "arm"),
        ({"arm_effects": {"b": math.inf}}, "finite"),
        ({"n_agq": 0}, "n_agq"),
    ],
)
def test_simulate_power_rejects_bad_input(kwargs: dict[str, Any], message: str) -> None:
    args: dict[str, Any] = {
        "base_rate": 0.3,
        "effects": {"M1": 0.5},
        "random_sd": 0.5,
        "n_tasks": 6,
        "runs_per_task_per_cell": 1,
        "n_sim": 2,
    }
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        simulate_power(**args)


# Sample-size search -----------------------------------------------------------------------

#: SYNTHETIC design parameters for the search tests: two manipulations (a full 2 x 2
#: factorial), a true effect of 1.5 log-odds for M1 and none for M2.
SEARCH_DESIGN: dict[str, Any] = {
    "base_rate": 0.3,
    "effects": {"M1": 1.5, "M2": 0.0},
    "random_sd": 0.5,
    "n_tasks": 6,
    "n_sim": 25,
    "seed": 3,
}


def min_power(result: PowerResult, names: tuple[str, ...]) -> float:
    """Smallest simulated power among the named effects."""
    return min(result.power_of(name).power for name in names)


def test_search_stops_at_the_smallest_sufficient_candidate() -> None:
    sizes = (1, 2, 4, 8, 16, 32)
    search = smallest_sufficient("replicates", sizes, 0.6, check=["M1"], **SEARCH_DESIGN)
    assert isinstance(search, SampleSizeSearch)
    assert search.parameter == "replicates" and search.check == ("M1",)
    assert search.target == 0.6
    assert search.chosen is not None
    assert search.candidates == sizes[: len(search.results)]
    assert search.chosen == search.candidates[-1]
    powers = [min_power(r, search.check) for r in search.results]
    assert powers[-1] >= 0.6 and all(p < 0.6 for p in powers[:-1])
    # Each candidate is a full simulation of the replicated design at that size.
    for size, result in zip(search.candidates, search.results, strict=True):
        assert result.layout == "replicated" and result.n_obs == 4 * size
        assert result.seed == SEARCH_DESIGN["seed"]


def test_search_checks_every_manipulation_by_default_and_can_fail() -> None:
    # M2 has a true effect of 0, so its power stays near alpha: no candidate suffices.
    design = {k: v for k, v in SEARCH_DESIGN.items() if k != "n_tasks"}
    search = smallest_sufficient("n_tasks", [4, 8], 0.9, **design)
    assert search.check == ("M1", "M2")
    assert search.chosen is None
    assert search.candidates == (4, 8)
    assert [r.n_tasks for r in search.results] == [4, 8]
    out = search.as_dict()
    assert out["synthetic"] is True and out["chosen"] is None
    assert [r["n_tasks"] for r in out["results"]] == [4, 8]


def test_search_over_runs_per_cell() -> None:
    design = SEARCH_DESIGN | {"effects": {"M1": 2.5}, "n_sim": 10}
    search = smallest_sufficient("runs_per_task_per_cell", [1, 3], 0.5, **design)
    assert search.chosen in (1, 3)
    assert search.results[0].n_obs == 6 * 2 * 1


@pytest.mark.parametrize(
    ("args", "kwargs", "message"),
    [
        (("cells", [1, 2], 0.8), {}, "parameter"),
        (("replicates", [], 0.8), {}, "at least one"),
        (("replicates", [2, 2], 0.8), {}, "increasing"),
        (("replicates", [3, 1], 0.8), {}, "increasing"),
        (("replicates", [1, 2], 1.0), {}, "target"),
        (("replicates", [1, 2], 0.0), {}, "target"),
        (("replicates", [1, 2], 0.8), {"check": []}, "check"),
        (("replicates", [1, 2], 0.8), {"check": ["M9"]}, "M9"),
        (("replicates", [1, 2], 0.8), {"replicates": 3}, "replicates"),
    ],
)
def test_search_rejects_bad_input(
    args: tuple[Any, ...], kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        smallest_sufficient(*args, **SEARCH_DESIGN | kwargs)


@pytest.mark.slow
def test_power_matches_the_exact_wald_power_closely() -> None:
    exact = two_group_wald_power(0.3, 0.8, n_per_cell=100, alpha=0.05)
    result = simulate_power(
        base_rate=0.3,
        effects={"M1": 0.8},
        random_sd=0.0,
        n_tasks=10,
        runs_per_task_per_cell=10,
        n_sim=1000,
        seed=13,
    )
    # 1000 datasets: Monte Carlo SD about 0.013; 0.05 is about 3.8 SD.
    assert result.power_of("M1").power == pytest.approx(exact, abs=0.05)


@pytest.mark.slow
def test_null_effect_rejects_at_about_alpha_with_many_datasets() -> None:
    # 1000 simulated datasets at alpha 0.05: 50 rejections expected, SD about 6.9.
    result = simulate_power(
        base_rate=0.3,
        effects={"M1": 0.0, "M2": 0.0},
        random_sd=1.0,
        n_tasks=20,
        runs_per_task_per_cell=2,
        n_sim=1000,
        seed=17,
    )
    for name in ("M1", "M2"):
        assert 25 <= result.power_of(name).rejections <= 75
