"""Simulation power analysis for factorial designs analysed with the random-intercept GLMM.

Data-generating model (the model :func:`receipts.analysis.glmm.fit_glmm` fits)::

    logit P(y = 1) = logit(base_rate) + sum_k effect_k * M_k + arm_effect + sd * u_task

with ``M_k`` in {0, 1} the level of manipulation ``k`` in the run's cell (0 is the
control level), ``arm_effect`` the log-odds of the run's arm relative to the
reference arm (0 for the reference), and ``u_task ~ N(0, 1)`` shared by every run
of a task in every arm. ``base_rate`` is the outcome probability for the reference
arm in the cell where every manipulation is 0, for a task whose random intercept is
0 (the median task); ``marginal_base_rate`` in the result averages it over tasks.

Layouts (runs per arm; every arm runs the identical list of task and cell pairs):

- crossed (default): every task runs every cell ``runs_per_task_per_cell`` times.
- replicated (``replicates=R``): the design of ``receipts.study.plan.factorial_plan``.
  The cell list repeated ``R`` times gives ``R * n_cells`` runs; tasks are assigned
  to them by cycling through the tasks and shuffling, so task counts differ by at
  most one (only the first ``R * n_cells`` tasks are used when there are more tasks
  than runs). The shuffle is redrawn for every simulated dataset, so power averages
  over the randomization.

Each simulated dataset draws (in this order, from ``numpy.random.default_rng(seed)``)
the task assignment when the layout is replicated, the task intercepts, and the
outcomes; it is then fitted with ``fit_glmm(n_agq=n_agq)``, the full model with every
manipulation and arm column, and each effect counts as detected when its two-sided
Wald p-value is at most ``alpha``. A dataset whose fit did not converge or showed
separation counts as a non-detection for every effect (conservative) and is
counted in ``n_failed``. Power is detections / ``n_sim`` with a Wilson 95 percent
Monte Carlo interval.

Speed: ``n_agq = 1`` (Laplace, the default) is the fast approximation; pass the
preregistered analysis's ``n_agq`` (for example 8) to simulate exactly that test.
Laplace and AGQ estimates usually differ little (``tests/analysis`` checks this);
the Wald tests are the same in kind. A fit takes tens of milliseconds at the size
of E1 (a few hundred runs, about ten fixed effects), so 1000 simulated datasets take
on the order of a minute on one CPU core.

Sample size: :func:`smallest_sufficient` evaluates increasing values of one design
size (replicates, tasks, or runs per task per cell) and stops at the first whose
simulated power reaches a target for every checked effect.

All simulated data is synthetic, and results are labeled so
(``as_dict()["synthetic"] is True``).
"""

from __future__ import annotations

import itertools
import math
import operator
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
from numpy.polynomial.hermite_e import hermegauss
from numpy.typing import NDArray
from scipy.special import expit, logit

from receipts.analysis.design import INTERCEPT, Design
from receipts.analysis.glmm import MAX_AGQ, fit_glmm
from receipts.analysis.rates import wilson_interval

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.intp]

METHOD = "simulation: random-intercept logistic data, fit_glmm Wald tests"


def _factor_names(factors: Sequence[str]) -> list[str]:
    names = [str(f) for f in factors]
    if any(not name for name in names):
        raise ValueError("factor names must be non-empty")
    if len(set(names)) != len(names):
        raise ValueError("factor names must be unique")
    return names


def full_factorial(factors: Sequence[str]) -> tuple[dict[str, int], ...]:
    """Every combination of levels 0 and 1 of each factor; the first factor varies slowest."""
    names = _factor_names(factors)
    return tuple(
        dict(zip(names, levels, strict=True))
        for levels in itertools.product((0, 1), repeat=len(names))
    )


def half_fraction(factors: Sequence[str], sign: int = 1) -> tuple[dict[str, int], ...]:
    """The 2^(k-1) half fraction with defining relation ``I = sign * (product of all factors)``.

    Levels 0 and 1 are multiplied as -1 and +1. With five factors and ``sign = 1`` these
    are the 16 cells of ``receipts.study.plan.half_fraction_cells`` (level 0 is a
    factor's first listed level). The resolution equals the number of factors.
    """
    if sign not in (1, -1):
        raise ValueError(f"sign must be 1 or -1, got {sign}")
    names = _factor_names(factors)
    if len(names) < 2:
        raise ValueError("a half fraction needs at least two factors")
    return tuple(
        cell
        for cell in full_factorial(names)
        if math.prod(2 * v - 1 for v in cell.values()) == sign
    )


@dataclass(frozen=True)
class EffectPower:
    """Power for one effect.

    Attributes:
        name: Column name of the effect (a manipulation, or ``arm[T.<arm>]``).
        log_odds: True effect used in the simulation.
        rejections: Datasets whose Wald test rejected at ``alpha``.
        rejections_correct_sign: Rejections whose estimate has the sign of the true
            effect (always 0 for a true effect of 0).
        power: ``rejections / n_sim``.
        ci_low: Lower bound of the Wilson 95 percent Monte Carlo interval.
        ci_high: Upper bound of that interval.
    """

    name: str
    log_odds: float
    rejections: int
    rejections_correct_sign: int
    power: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class PowerResult:
    """Simulated power for every effect of one design (all data synthetic).

    Attributes:
        effects: Power per effect, manipulations first, then arms.
        n_sim: Simulated datasets.
        n_failed: Datasets whose fit did not converge or showed separation.
        n_obs: Runs per dataset (all arms).
        n_tasks: Tasks with at least one run.
        n_cells: Cells in the design.
        n_arms: Arms, including the reference arm.
        layout: ``"crossed"`` or ``"replicated"`` (module docstring).
        base_rate: Reference-cell probability for the median task (an input).
        marginal_base_rate: Reference-cell probability averaged over tasks.
        mean_outcome_rate: Mean outcome over every simulated run.
        random_sd: Task random-intercept SD on the logit scale (an input).
        alpha: Two-sided significance level of each Wald test.
        n_agq: Quadrature nodes used by the fits.
        seed: Seed of ``numpy.random.default_rng``.
    """

    effects: tuple[EffectPower, ...]
    n_sim: int
    n_failed: int
    n_obs: int
    n_tasks: int
    n_cells: int
    n_arms: int
    layout: Literal["crossed", "replicated"]
    base_rate: float
    marginal_base_rate: float
    mean_outcome_rate: float
    random_sd: float
    alpha: float
    n_agq: int
    seed: int

    def power_of(self, name: str) -> EffectPower:
        """The result for one effect; raises KeyError if absent."""
        for effect in self.effects:
            if effect.name == name:
                return effect
        raise KeyError(name)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready mapping, labeled synthetic, with the method description."""
        out = asdict(self)
        out["effects"] = [asdict(e) for e in self.effects]
        out.update(method=METHOD, synthetic=True)
        return out


def _positive_int(value: int, name: str, minimum: int) -> int:
    number = operator.index(value)
    if number < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {number}")
    return number


def _finite_effects(effects: Mapping[str, float], what: str) -> dict[str, float]:
    out = {str(k): float(v) for k, v in effects.items()}
    if any(not k for k in out):
        raise ValueError(f"{what} names must be non-empty")
    if not all(math.isfinite(v) for v in out.values()):
        raise ValueError(f"{what} log-odds must be finite")
    return out


def _cell_matrix(cells: Sequence[Mapping[str, int]], names: Sequence[str]) -> FloatArray:
    rows = []
    for cell in cells:
        if set(cell) != set(names):
            raise ValueError(f"each cell must give a level for exactly {sorted(names)}")
        if any(cell[n] not in (0, 1) for n in names):
            raise ValueError("cell levels must be 0 or 1")
        rows.append([float(cell[n]) for n in names])
    return np.array(rows, dtype=np.float64).reshape(len(rows), len(names))


def _marginal_rate(eta: float, sd: float) -> float:
    nodes, weights = hermegauss(40)
    return float(np.sum(weights * expit(eta + sd * nodes)) / math.sqrt(2.0 * math.pi))


def simulate_power(
    base_rate: float,
    effects: Mapping[str, float],
    random_sd: float,
    n_tasks: int,
    runs_per_task_per_cell: int = 1,
    alpha: float = 0.05,
    n_sim: int = 500,
    seed: int = 0,
    *,
    cells: Sequence[Mapping[str, int]] | None = None,
    replicates: int | None = None,
    arm_effects: Mapping[str, float] | None = None,
    n_agq: int = 1,
) -> PowerResult:
    """Simulated power of the GLMM Wald test for each effect (see the module docstring).

    Args:
        base_rate: Reference-cell probability for the median task, in ``(0, 1)``.
        effects: Log-odds effect of each manipulation (level 1 versus level 0).
        random_sd: Task random-intercept SD on the logit scale, at least 0.
        n_tasks: Number of tasks, at least 2.
        runs_per_task_per_cell: Runs of each cell per task (crossed layout).
        alpha: Two-sided significance level of each test.
        n_sim: Number of simulated datasets.
        seed: Seed for ``numpy.random.default_rng``.
        cells: Cells to run (each maps every manipulation to 0 or 1); default the full
            factorial over ``effects``.
        replicates: Use the replicated layout with this many copies of the cell list.
        arm_effects: Log-odds of each extra arm relative to the reference arm.
        n_agq: Quadrature nodes for the fits (1 is the Laplace approximation).

    Raises:
        ValueError: An input is out of range, the cells are invalid, or the design
            matrix is rank deficient.
    """
    if not 0.0 < base_rate < 1.0:
        raise ValueError(f"base_rate must be in (0, 1), got {base_rate}")
    if not effects:
        raise ValueError("give at least one manipulation effect")
    manipulation = _finite_effects(effects, "effect")
    arms = _finite_effects(arm_effects or {}, "arm effect")
    if set(arms) & set(manipulation):
        raise ValueError("arm names must differ from manipulation names")
    if not (math.isfinite(random_sd) and random_sd >= 0.0):
        raise ValueError(f"random_sd must be finite and at least 0, got {random_sd}")
    n_tasks = _positive_int(n_tasks, "n_tasks", 2)
    per_cell = _positive_int(runs_per_task_per_cell, "runs_per_task_per_cell", 1)
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    n_sim = _positive_int(n_sim, "n_sim", 1)
    n_agq = operator.index(n_agq)
    if not 1 <= n_agq <= MAX_AGQ:
        raise ValueError(f"n_agq must be between 1 and {MAX_AGQ}, got {n_agq}")
    names = list(manipulation)
    cell_list = full_factorial(names) if cells is None else list(cells)
    cell_x = _cell_matrix(cell_list, names)
    n_cells = cell_x.shape[0]
    layout: Literal["crossed", "replicated"]
    if replicates is None:
        layout = "crossed"
        slot_cells = np.tile(np.repeat(np.arange(n_cells), per_cell), n_tasks)
        slot_tasks = np.repeat(np.arange(n_tasks), n_cells * per_cell)
    else:
        if per_cell != 1:
            raise ValueError("give either runs_per_task_per_cell or replicates, not both")
        reps = _positive_int(replicates, "replicates", 1)
        layout = "replicated"
        slot_cells = np.tile(np.arange(n_cells), reps)
        slot_tasks = np.arange(slot_cells.size) % n_tasks
    n_arms = 1 + len(arms)
    n_slots = slot_cells.size
    arm_of_run = np.repeat(np.arange(n_arms), n_slots)
    x = np.column_stack(
        [
            np.ones(n_arms * n_slots),
            np.tile(cell_x[slot_cells], (n_arms, 1)),
            (arm_of_run[:, None] == np.arange(1, n_arms)[None, :]).astype(np.float64),
        ]
    )
    columns = (INTERCEPT, *names, *(f"arm[T.{a}]" for a in arms))
    truth = np.array([float(logit(base_rate)), *manipulation.values(), *arms.values()])
    template = Design(
        x=x, y=np.zeros(x.shape[0]), column_names=columns, groups=np.tile(slot_tasks, n_arms)
    )
    fixed = template.x @ truth
    rng = np.random.default_rng(seed)
    tested = range(1, len(columns))
    rejections = np.zeros(len(columns), dtype=int)
    right_sign = np.zeros(len(columns), dtype=int)
    failed = 0
    outcome_total = 0.0
    for _ in range(n_sim):
        tasks = rng.permutation(slot_tasks) if layout == "replicated" else slot_tasks
        groups = np.tile(tasks, n_arms)
        intercepts = random_sd * rng.standard_normal(template.n_groups)
        y = (rng.random(template.n_obs) < expit(fixed + intercepts[groups])).astype(np.float64)
        outcome_total += float(y.mean())
        fit = fit_glmm(Design(x=template.x, y=y, column_names=columns, groups=groups), n_agq=n_agq)
        if not fit.converged or fit.separation:
            failed += 1
            continue
        p_values, coef = fit.p_values, fit.coef
        for j in tested:
            if p_values[j] <= alpha:
                rejections[j] += 1
                right_sign[j] += int(truth[j] != 0.0 and np.sign(coef[j]) == np.sign(truth[j]))
    results = []
    for j in tested:
        low, high = wilson_interval(int(rejections[j]), n_sim)
        results.append(
            EffectPower(
                name=columns[j],
                log_odds=float(truth[j]),
                rejections=int(rejections[j]),
                rejections_correct_sign=int(right_sign[j]),
                power=float(rejections[j]) / n_sim,
                ci_low=low,
                ci_high=high,
            )
        )
    return PowerResult(
        effects=tuple(results),
        n_sim=n_sim,
        n_failed=failed,
        n_obs=template.n_obs,
        n_tasks=template.n_groups,
        n_cells=n_cells,
        n_arms=n_arms,
        layout=layout,
        base_rate=float(base_rate),
        marginal_base_rate=_marginal_rate(float(truth[0]), float(random_sd)),
        mean_outcome_rate=outcome_total / n_sim,
        random_sd=float(random_sd),
        alpha=float(alpha),
        n_agq=n_agq,
        seed=seed,
    )


SEARCHABLE = ("replicates", "n_tasks", "runs_per_task_per_cell")
"""Design sizes that :func:`smallest_sufficient` can search over."""


@dataclass(frozen=True)
class SampleSizeSearch:
    """The smallest design size whose simulated power reaches a target (synthetic data).

    Attributes:
        parameter: The design size searched, one of ``SEARCHABLE``.
        target: Power that every checked effect must reach (the simulated estimate,
            not a bound of its Monte Carlo interval).
        check: Names of the effects whose power is checked.
        chosen: The smallest candidate that met the target, or None if none did.
        candidates: The candidates evaluated, in increasing order; the search stops at
            the first one that meets the target.
        results: The power simulation of each evaluated candidate.
    """

    parameter: str
    target: float
    check: tuple[str, ...]
    chosen: int | None
    candidates: tuple[int, ...]
    results: tuple[PowerResult, ...]

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready mapping, labeled synthetic, including every evaluated simulation."""
        return {
            "parameter": self.parameter,
            "target": self.target,
            "check": list(self.check),
            "chosen": self.chosen,
            "candidates": list(self.candidates),
            "results": [result.as_dict() for result in self.results],
            "synthetic": True,
        }


def smallest_sufficient(
    parameter: Literal["replicates", "n_tasks", "runs_per_task_per_cell"],
    candidates: Sequence[int],
    target: float,
    *,
    check: Sequence[str] | None = None,
    **design: Any,
) -> SampleSizeSearch:
    """Smallest value of one design size at which every checked effect has power >= target.

    Runs :func:`simulate_power` with the arguments in ``design`` and ``parameter`` set
    to each candidate, in increasing order, and stops at the first candidate at which
    the simulated power of every effect in ``check`` is at least ``target``: the rule
    of a preregistered sample size such as "the smallest replicate count with power
    of at least 0.8". Every candidate uses the same ``seed`` from ``design``. The
    rule uses the simulated power itself; report each result's Monte Carlo interval
    beside it.

    Args:
        parameter: ``"replicates"``, ``"n_tasks"``, or ``"runs_per_task_per_cell"``.
        candidates: Strictly increasing values to try.
        target: Required power, in ``(0, 1)``.
        check: Effect names to check (manipulations, or ``arm[T.<arm>]``); default
            every manipulation in ``design["effects"]`` and no arm effect (a null arm
            effect is rejected only at about ``alpha``, so it can never reach a target
            power and must be named explicitly to be checked).
        **design: The other arguments of :func:`simulate_power`.

    Raises:
        ValueError: An argument is invalid, ``design`` also sets ``parameter``, a
            checked name is not an effect of the design, or :func:`simulate_power`
            rejects the design.
    """
    if parameter not in SEARCHABLE:
        raise ValueError(f"parameter must be one of {', '.join(SEARCHABLE)}, got {parameter!r}")
    if parameter in design:
        raise ValueError(f"{parameter} is the searched size; do not also pass it in the design")
    sizes = [operator.index(value) for value in candidates]
    if not sizes:
        raise ValueError("give at least one candidate size")
    if any(later <= earlier for earlier, later in itertools.pairwise(sizes)):
        raise ValueError(f"candidate sizes must be strictly increasing, got {sizes}")
    if not 0.0 < target < 1.0:
        raise ValueError(f"target must be in (0, 1), got {target}")
    manipulations = [str(name) for name in design.get("effects") or {}]
    known = [*manipulations, *(f"arm[T.{arm}]" for arm in design.get("arm_effects") or {})]
    if check is None:
        names = manipulations
    else:
        names = [check] if isinstance(check, str) else [str(name) for name in check]
    if not names:
        raise ValueError("check must name at least one effect")
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError("check names effects the design does not have: " + ", ".join(unknown))
    results: list[PowerResult] = []
    chosen: int | None = None
    for size in sizes:
        arguments: dict[str, Any] = {**design, parameter: size}
        result = simulate_power(**arguments)
        results.append(result)
        if all(result.power_of(name).power >= target for name in names):
            chosen = size
            break
    return SampleSizeSearch(
        parameter=parameter,
        target=float(target),
        check=tuple(names),
        chosen=chosen,
        candidates=tuple(sizes[: len(results)]),
        results=tuple(results),
    )
