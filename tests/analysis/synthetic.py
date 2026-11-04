"""Synthetic data for the analysis tests.

Everything here is generated from fixed seeds by a known random-intercept logistic
model. None of it is agent data, and no result computed from it is a study result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy.special import expit

from receipts.analysis.design import Design, Formula, build_design

#: Formula for the synthetic records below: factors A (a0, a1) and B (b0, b1, b2).
FORMULA = Formula(response="y", factors=("A", "B"), group="task")

#: Column names of FORMULA's design, in order.
COLUMNS = ("(Intercept)", "A[T.a1]", "B[T.b1]", "B[T.b2]")


def synthetic_records(
    seed: int,
    n_tasks: int,
    runs_per_task: int,
    coef: Mapping[str, float],
    sd: float,
) -> list[dict[str, Any]]:
    """SYNTHETIC records from logit p = x'coef + sd * u_task with u_task ~ N(0, 1).

    Each run draws A uniformly from (a0, a1) and B uniformly from (b0, b1, b2).
    ``coef`` maps the names in COLUMNS to their true values.
    """
    rng = np.random.default_rng(seed)
    u = rng.normal(0.0, 1.0, n_tasks)
    records: list[dict[str, Any]] = []
    for task in range(n_tasks):
        for _ in range(runs_per_task):
            a = int(rng.integers(2))
            b = int(rng.integers(3))
            eta = (
                coef["(Intercept)"]
                + coef["A[T.a1]"] * (a == 1)
                + coef["B[T.b1]"] * (b == 1)
                + coef["B[T.b2]"] * (b == 2)
                + sd * u[task]
            )
            y = int(rng.random() < float(expit(eta)))
            records.append(
                {"task": f"task{task:03d}", "A": f"a{a}", "B": f"b{b}", "y": y, "synthetic": True}
            )
    return records


def synthetic_design(
    seed: int, n_tasks: int, runs_per_task: int, coef: Mapping[str, float], sd: float
) -> Design:
    """The design of :func:`synthetic_records` (SYNTHETIC data)."""
    return build_design(synthetic_records(seed, n_tasks, runs_per_task, coef, sd), FORMULA)


#: True coefficients used by several tests (design parameters of the synthetic data).
TRUE_COEF: dict[str, float] = {
    "(Intercept)": -0.6,
    "A[T.a1]": 0.9,
    "B[T.b1]": -0.5,
    "B[T.b2]": 0.4,
}
