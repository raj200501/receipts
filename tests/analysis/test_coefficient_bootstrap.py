"""Tests for receipts.analysis.glmm.bootstrap_coefficients.

Every dataset here is SYNTHETIC: generated from fixed seeds by the known model in
tests/analysis/synthetic.py, or written by hand for one property. None of it is
agent data and no number here is a study result.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from receipts.analysis import glmm
from receipts.analysis.design import Design, Formula, build_design
from receipts.analysis.glmm import bootstrap_coefficients, fit_glmm, fit_logistic
from receipts.analysis.rates import BootstrapResult, cluster_bootstrap_many, relabel_field
from tests.analysis.synthetic import COLUMNS, FORMULA, TRUE_COEF, synthetic_records


def manual_bootstrap(
    records: list[dict[str, Any]], formula: Formula, n_boot: int, seed: int
) -> dict[str, BootstrapResult]:
    """The documented algorithm, written out with the public building blocks."""
    assert formula.group is not None
    original = build_design(records, formula)
    fixed = replace(formula, reference={f: original.levels[f][0] for f in formula.factors})

    def coefficients(rows: Any) -> dict[str, float]:
        try:
            design = build_design(rows, fixed)
        except ValueError:
            return {}
        fit = fit_logistic(design)
        if not fit.converged or fit.separation:
            return {}
        return dict(zip(fit.column_names, map(float, fit.coef), strict=True))

    return cluster_bootstrap_many(
        records,
        coefficients,
        formula.group,
        n_boot,
        seed,
        names=original.column_names,
        relabel=relabel_field(formula.group),
    )


def test_logistic_bootstrap_follows_the_documented_algorithm() -> None:
    records = synthetic_records(seed=4, n_tasks=15, runs_per_task=8, coef=TRUE_COEF, sd=0.5)
    out = bootstrap_coefficients(records, FORMULA, model="logistic", n_boot=40, seed=9)
    assert list(out) == list(COLUMNS)
    assert out == manual_bootstrap(records, FORMULA, n_boot=40, seed=9)


def test_glmm_bootstrap_intervals_are_sensible(monkeypatch: pytest.MonkeyPatch) -> None:
    records = synthetic_records(seed=12, n_tasks=24, runs_per_task=10, coef=TRUE_COEF, sd=0.8)
    fit = fit_glmm(build_design(records, FORMULA), n_agq=3)
    clusters_seen: list[int] = []
    real_fit = glmm.fit_glmm

    def recording_fit(design: Design, n_agq: int = 1) -> glmm.FitResult:
        clusters_seen.append(design.n_groups)
        return real_fit(design, n_agq=n_agq)

    monkeypatch.setattr(glmm, "fit_glmm", recording_fit)
    out = bootstrap_coefficients(records, FORMULA, n_agq=3, n_boot=30, seed=5)
    # A task drawn twice is two clusters: every replicate fit sees 24 clusters.
    assert clusters_seen == [24] * 31
    for name in COLUMNS:
        result = out[name]
        assert isinstance(result, BootstrapResult)
        assert result.estimate == pytest.approx(fit.coefficient(name).estimate, abs=1e-12)
        assert result.ci_low < result.estimate < result.ci_high
        assert (result.n_boot, result.n_clusters, result.n_nonfinite) == (30, 24, 0)
        wald = fit.coefficient(name)
        ratio = (result.ci_high - result.ci_low) / (wald.ci_high - wald.ci_low)
        assert 0.5 < ratio < 2.0


def test_replicates_without_the_reference_level_are_dropped() -> None:
    # SYNTHETIC, hand-written: the reference level a0 occurs only in tasks t0 and t1,
    # and every level has both outcomes inside each task that has it.
    records = []
    for t in range(8):
        rows = (
            [("a0", 0), ("a0", 1), ("a1", 0), ("a1", 1)] if t < 2 else [("a1", y) for y in (0, 1)]
        )
        records += [{"task": f"t{t}", "A": a, "y": y} for a, y in rows]
    formula = Formula("y", ("A",), group="task")
    out = bootstrap_coefficients(records, formula, model="logistic", n_boot=200, seed=3)
    # Clusters are numbered by first appearance, so t0 and t1 are 0 and 1: replicates
    # that draw neither cannot build the design and are NaN for every term.
    draws = np.random.default_rng(3).integers(0, 8, size=(200, 8))
    missing = int(np.sum(~np.any(draws < 2, axis=1)))
    assert missing > 0
    assert out["(Intercept)"].n_nonfinite == out["A[T.a1]"].n_nonfinite == missing


def test_replicates_without_a_non_reference_level_lose_that_column_only() -> None:
    # SYNTHETIC: level b2 occurs only in task t0 (with both outcomes).
    rng = np.random.default_rng(1)
    records = [
        {"task": f"t{t}", "B": b, "y": int(rng.random() < 0.4)}
        for t in range(8)
        for b in ("b0", "b1", "b0", "b1", "b0", "b1")
    ]
    records += [{"task": "t0", "B": "b2", "y": y} for y in (0, 1, 1)]
    formula = Formula("y", ("B",), group="task")
    out = bootstrap_coefficients(records, formula, model="logistic", n_boot=150, seed=2)
    assert 0 < out["B[T.b2]"].n_nonfinite < 150
    assert out["B[T.b1]"].n_nonfinite < out["B[T.b2]"].n_nonfinite
    assert math.isfinite(out["B[T.b2]"].ci_low)


def test_a_separated_original_fit_gives_nan_estimates() -> None:
    # SYNTHETIC: A = a1 always has y = 1, in every task, so every fit is separated.
    records = [
        {"task": t, "A": a, "y": 1 if a == "a1" else int(i % 2 == 0)}
        for t in range(5)
        for a in ("a0", "a1")
        for i in range(4)
    ]
    out = bootstrap_coefficients(
        records, Formula("y", ("A",), group="task"), model="logistic", n_boot=20
    )
    for result in out.values():
        assert math.isnan(result.estimate) and result.n_nonfinite == 20


@pytest.mark.parametrize(
    ("formula", "kwargs", "message"),
    [
        (Formula("y", ("A", "B")), {}, "formula.group"),
        (FORMULA, {"model": "probit"}, "model"),
        (FORMULA, {"n_agq": 0}, "n_agq"),
        (FORMULA, {"n_boot": 0}, "n_boot"),
        (FORMULA, {"level": 1.0}, "level"),
    ],
)
def test_bootstrap_coefficients_rejects_bad_input(
    formula: Formula, kwargs: dict[str, Any], message: str
) -> None:
    records = synthetic_records(seed=1, n_tasks=4, runs_per_task=6, coef=TRUE_COEF, sd=0.5)
    with pytest.raises(ValueError, match=message):
        bootstrap_coefficients(records, formula, **kwargs)
