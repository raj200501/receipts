"""Tests for receipts.analysis.glmm.

Validation is on SYNTHETIC data only (tests/analysis/synthetic.py and small
hand-written tables): the true parameters are known because the test generated
the data.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np
import pytest
from scipy import integrate
from scipy.special import expit, log_expit
from scipy.stats import chi2, norm

from receipts.analysis import glmm
from receipts.analysis.design import Design, Formula, build_design
from receipts.analysis.glmm import (
    CHECK_AGQ,
    QUADRATURE_TOL,
    SD_LIMIT,
    Coefficient,
    FitResult,
    detect_separation,
    fit_glmm,
    fit_logistic,
    likelihood_ratio_test,
    marginal_log_likelihood,
    marginal_score,
)
from tests.analysis.synthetic import (
    COLUMNS,
    TRUE_COEF,
    separated_arm_records,
    synthetic_design,
)

FloatArray = np.ndarray[Any, np.dtype[np.float64]]


def brute_force_loglik(design: Design, coef: FloatArray, sd: float) -> float:
    """Marginal log-likelihood by adaptive numerical integration (scipy quad)."""
    assert design.groups is not None
    eta = design.x @ coef
    total = 0.0
    for g in range(design.n_groups):
        mask = design.groups == g
        y, offset = design.y[mask], eta[mask]

        def log_integrand(u: float, y: FloatArray = y, offset: FloatArray = offset) -> float:
            lin = offset + sd * u
            return float(np.sum(y * log_expit(lin) + (1 - y) * log_expit(-lin))) - 0.5 * u * u

        peak = max(log_integrand(u) for u in np.linspace(-8, 8, 161))

        def integrand(u: float, peak: float = peak) -> float:
            return math.exp(log_integrand(u) - peak)

        value, _ = integrate.quad(integrand, -np.inf, np.inf, epsabs=0, epsrel=1e-12)
        total += peak + math.log(value) - 0.5 * math.log(2 * math.pi)
    return total


def brute_force_hessian(design: Design, theta: FloatArray, h: float = 1e-3) -> FloatArray:
    """Central differences of minus :func:`brute_force_loglik` over ``(coef..., sd)``."""
    p = design.n_params

    def f(t: FloatArray) -> float:
        return -brute_force_loglik(design, t[:p], float(t[p]))

    centre = f(theta)
    step = h * np.eye(theta.size)
    hessian = np.empty((theta.size, theta.size))
    for i in range(theta.size):
        hessian[i, i] = (f(theta + step[i]) - 2.0 * centre + f(theta - step[i])) / (h * h)
        for j in range(i + 1, theta.size):
            hessian[i, j] = hessian[j, i] = (
                f(theta + step[i] + step[j])
                - f(theta + step[i] - step[j])
                - f(theta - step[i] + step[j])
                + f(theta - step[i] - step[j])
            ) / (4.0 * h * h)
    return hessian


@pytest.fixture(scope="module")
def small() -> Design:
    """SYNTHETIC: 6 tasks of 5 runs with a sizable task SD."""
    return synthetic_design(seed=3, n_tasks=6, runs_per_task=5, coef=TRUE_COEF, sd=1.3)


@pytest.fixture(scope="module")
def clustered() -> Design:
    """SYNTHETIC: 80 tasks of 30 runs, task SD 1.0."""
    return synthetic_design(seed=11, n_tasks=80, runs_per_task=30, coef=TRUE_COEF, sd=1.0)


@pytest.fixture(scope="module")
def unclustered() -> Design:
    """SYNTHETIC: 50 tasks of 20 runs with no task effect (true SD 0)."""
    return synthetic_design(seed=5, n_tasks=50, runs_per_task=20, coef=TRUE_COEF, sd=0.0)


# The marginal likelihood ---------------------------------------------------------


def test_agq_matches_numerical_integration(small: Design) -> None:
    coef = np.array([-0.3, 0.8, -0.2, 0.5])
    exact = brute_force_loglik(small, coef, 1.4)
    assert marginal_log_likelihood(small, coef, 1.4, n_agq=25) == pytest.approx(exact, abs=1e-8)
    agq9 = marginal_log_likelihood(small, coef, 1.4, n_agq=9)
    assert agq9 == pytest.approx(exact, abs=1e-4)
    # Laplace (one node) is an approximation: close, but less accurate than 9 nodes.
    laplace = marginal_log_likelihood(small, coef, 1.4, n_agq=1)
    assert laplace == pytest.approx(exact, abs=0.25)
    assert abs(laplace - exact) > 10 * abs(agq9 - exact)


def test_zero_sd_gives_the_logistic_likelihood(small: Design) -> None:
    coef = np.array([0.2, -0.4, 0.3, 0.1])
    eta = small.x @ coef
    logistic = float(np.sum(small.y * log_expit(eta) + (1 - small.y) * log_expit(-eta)))
    for n_agq in (1, 4, 15):
        assert marginal_log_likelihood(small, coef, 0.0, n_agq) == pytest.approx(
            logistic, abs=1e-10
        )


def test_likelihood_is_even_in_sd(small: Design) -> None:
    coef = np.array([-0.3, 0.8, -0.2, 0.5])
    for n_agq in (1, 6):
        pos = marginal_log_likelihood(small, coef, 0.9, n_agq)
        assert marginal_log_likelihood(small, coef, -0.9, n_agq) == pytest.approx(pos, abs=1e-10)


@pytest.mark.parametrize("n_agq", [1, 2, 7])
@pytest.mark.parametrize("sd", [0.0, 0.6, 2.5, -1.1])
def test_score_matches_finite_differences(small: Design, n_agq: int, sd: float) -> None:
    theta = np.array([-0.3, 0.8, -0.2, 0.5, sd])

    def f(t: FloatArray) -> float:
        return marginal_log_likelihood(small, t[:-1], float(t[-1]), n_agq)

    numeric = np.empty_like(theta)
    for j in range(theta.size):
        h = 1e-5
        up, down = theta.copy(), theta.copy()
        up[j] += h
        down[j] -= h
        numeric[j] = (f(up) - f(down)) / (2 * h)
    analytic = marginal_score(small, theta[:-1], sd, n_agq)
    assert analytic == pytest.approx(numeric, abs=1e-6, rel=1e-6)


def test_marginal_functions_validate_input(small: Design) -> None:
    with pytest.raises(ValueError, match="coefficients"):
        marginal_log_likelihood(small, np.zeros(3), 1.0)
    with pytest.raises(ValueError, match="n_agq"):
        marginal_score(small, np.zeros(4), 1.0, n_agq=0)
    ungrouped = Design(x=small.x, y=small.y, column_names=small.column_names)
    with pytest.raises(ValueError, match="clusters"):
        marginal_log_likelihood(ungrouped, np.zeros(4), 1.0)


# Plain logistic regression -------------------------------------------------------


def two_by_two() -> Design:
    """SYNTHETIC 2x2 table: 3 of 10 events at a0, 7 of 10 at a1."""
    records = [{"A": "a0", "y": int(i < 3)} for i in range(10)]
    records += [{"A": "a1", "y": int(i < 7)} for i in range(10)]
    return build_design(records, Formula("y", ("A",)))


def test_logistic_matches_closed_form_for_a_two_by_two_table() -> None:
    fit = fit_logistic(two_by_two())
    assert fit.model == "logistic" and fit.converged and not fit.separation
    assert fit.coef == pytest.approx([math.log(3 / 7), 2 * math.log(7 / 3)], abs=1e-10)
    # Woolf's closed-form standard errors for a saturated 2x2 logistic model.
    assert fit.se == pytest.approx([math.sqrt(1 / 3 + 1 / 7), math.sqrt(2 / 3 + 2 / 7)], rel=1e-8)
    loglik = 2 * (3 * math.log(0.3) + 7 * math.log(0.7))
    assert fit.log_likelihood == pytest.approx(loglik, abs=1e-10)
    assert fit.aic == pytest.approx(-2 * loglik + 4, abs=1e-9)
    assert fit.random_sd is None and fit.n_groups is None and fit.n_agq is None
    assert (fit.n_obs, fit.n_events, fit.n_params) == (20, 10, 2)


def test_wald_quantities_follow_from_estimates(clustered: Design) -> None:
    fit = fit_logistic(clustered, level=0.9)
    se = np.sqrt(np.diag(fit.cov))
    assert fit.se == pytest.approx(se)
    assert fit.z == pytest.approx(fit.coef / se)
    assert fit.p_values == pytest.approx(2 * norm.sf(np.abs(fit.coef / se)))
    q = norm.ppf(0.95)
    assert fit.ci_low == pytest.approx(fit.coef - q * se)
    assert fit.ci_high == pytest.approx(fit.coef + q * se)


# The mixed model --------------------------------------------------------------------


def test_glmm_recovers_fixed_effects_and_sd(clustered: Design) -> None:
    fit = fit_glmm(clustered, n_agq=8)
    assert fit.converged and not fit.separation and fit.warnings == ()
    assert fit.column_names == COLUMNS
    truth = np.array([TRUE_COEF[c] for c in COLUMNS])
    assert np.all(np.abs(fit.coef - truth) < 3.5 * fit.se)
    assert np.all(np.abs(fit.coef - truth) < 0.3)
    assert fit.random_sd is not None
    assert abs(fit.random_sd - 1.0) < 0.2
    assert (fit.n_groups, fit.n_agq, fit.n_params) == (80, 8, 5)
    # The estimate is a stationary point of the likelihood it reports.
    score = marginal_score(clustered, fit.coef, fit.random_sd, 8)
    assert np.max(np.abs(score)) < 1e-4
    assert fit.log_likelihood == pytest.approx(
        marginal_log_likelihood(clustered, fit.coef, fit.random_sd, 8), abs=1e-9
    )
    for sd in (fit.random_sd - 0.05, fit.random_sd + 0.05):
        assert marginal_log_likelihood(clustered, fit.coef, sd, 8) < fit.log_likelihood


def test_glmm_covariance_is_the_inverse_observed_information(small: Design) -> None:
    # The covariance must be the fixed-effect block of the inverse information over all
    # parameters, the SD included. On this SYNTHETIC design, inverting the fixed-effect
    # block alone (treating the SD as known) gives SEs up to about 4 percent too small.
    fit = fit_glmm(small, n_agq=25)  # 25 nodes: the exact likelihood to about 1e-8
    assert fit.converged and fit.random_sd is not None and fit.random_sd > 0.5
    hessian = brute_force_hessian(small, np.append(fit.coef, fit.random_sd))
    p = small.n_params
    cov = np.linalg.inv(hessian)[:p, :p]
    assert fit.cov == pytest.approx(cov, rel=1e-4, abs=1e-6)
    assert fit.se == pytest.approx(np.sqrt(np.diag(cov)), rel=1e-4)
    sd_known = np.sqrt(np.diag(np.linalg.inv(hessian[:p, :p])))
    assert np.max(np.abs(sd_known / fit.se - 1.0)) > 0.02  # the test can tell them apart


def test_glmm_equals_logistic_when_true_sd_is_zero(unclustered: Design) -> None:
    mixed = fit_glmm(unclustered, n_agq=5)
    plain = fit_logistic(unclustered)
    assert mixed.converged and plain.converged
    assert mixed.random_sd is not None and mixed.random_sd < 0.3
    assert mixed.coef == pytest.approx(plain.coef, abs=0.05)
    assert mixed.se == pytest.approx(plain.se, rel=0.05)
    assert mixed.log_likelihood >= plain.log_likelihood - 1e-9
    assert mixed.log_likelihood - plain.log_likelihood < 1.0


def test_glmm_at_zero_sd_reproduces_logistic_exactly() -> None:
    # SYNTHETIC: every task has the same events in each cell, so the MLE of the SD is 0.
    records = []
    for task in range(8):
        for a in ("a0", "a1"):
            for i in range(4):
                records.append({"task": task, "A": a, "y": int(i < (1 if a == "a0" else 3))})
    design = build_design(records, Formula("y", ("A",), group="task"))
    mixed = fit_glmm(design, n_agq=3)
    plain = fit_logistic(design)
    assert mixed.random_sd is not None and mixed.random_sd < 1e-3
    assert mixed.converged
    assert mixed.coef == pytest.approx(plain.coef, abs=1e-5)
    assert mixed.se == pytest.approx(plain.se, rel=1e-3)
    assert mixed.log_likelihood == pytest.approx(plain.log_likelihood, abs=1e-8)


def test_more_quadrature_points_change_estimates_little() -> None:
    # SYNTHETIC: small clusters and a large SD, where Laplace is least accurate.
    design = synthetic_design(seed=21, n_tasks=40, runs_per_task=8, coef=TRUE_COEF, sd=1.5)
    fits = {n: fit_glmm(design, n_agq=n) for n in (1, 5, 12)}
    assert all(f.converged for f in fits.values())
    sds = {n: f.random_sd for n, f in fits.items()}
    assert fits[5].coef == pytest.approx(fits[12].coef, abs=5e-3)
    assert fits[1].coef == pytest.approx(fits[12].coef, abs=0.1)
    assert sds[5] == pytest.approx(sds[12], abs=5e-3)
    assert sds[1] == pytest.approx(sds[12], abs=0.15)


def test_glmm_input_validation(clustered: Design) -> None:
    ungrouped = Design(x=clustered.x, y=clustered.y, column_names=clustered.column_names)
    with pytest.raises(ValueError, match="clusters"):
        fit_glmm(ungrouped)
    one_group = Design(
        x=clustered.x,
        y=clustered.y,
        column_names=clustered.column_names,
        groups=np.zeros(clustered.n_obs, dtype=np.intp),
    )
    with pytest.raises(ValueError, match="at least two clusters"):
        fit_glmm(one_group)
    with pytest.raises(ValueError, match="n_agq"):
        fit_glmm(clustered, n_agq=0)
    with pytest.raises(ValueError, match="n_agq"):
        fit_glmm(clustered, n_agq=glmm.MAX_AGQ + 1)
    with pytest.raises(ValueError, match="level"):
        fit_glmm(clustered, level=1.5)


# Reporting -------------------------------------------------------------------------


def test_fit_result_lookup_table_and_dict(unclustered: Design) -> None:
    fit = fit_glmm(unclustered)
    first = fit.coefficient("A[T.a1]")
    assert isinstance(first, Coefficient)
    j = fit.index("A[T.a1]")
    assert first.estimate == fit.coef[j] and first.se == fit.se[j]
    assert (first.ci_low, first.ci_high) == (fit.ci_low[j], fit.ci_high[j])
    assert [c.name for c in fit.table()] == list(COLUMNS)
    with pytest.raises(KeyError):
        fit.index("missing")
    out = fit.as_dict()
    assert out["model"] == "glmm"
    assert [t["name"] for t in out["terms"]] == list(COLUMNS)
    assert out["terms"][j]["p_value"] == fit.p_values[j]
    assert out["cov"] == fit.cov.tolist()
    assert out["random_sd"] == fit.random_sd
    assert out["aic"] == fit.aic
    assert set(out) >= {"log_likelihood", "converged", "separation", "warnings", "n_obs"}
    with pytest.raises(ValueError):
        fit.coef[0] = 1.0  # read-only


# Separation ------------------------------------------------------------------------


def separated_records(complete: bool) -> list[dict[str, Any]]:
    """SYNTHETIC: A=a1 always has y=1; with ``complete`` A=a0 always has y=0."""
    records = []
    for task in range(6):
        for i in range(6):
            records.append({"task": task, "A": "a1", "B": f"b{i % 2}", "y": 1})
            y0 = 0 if complete else int(i % 3 == 0)
            records.append({"task": task, "A": "a0", "B": f"b{i % 2}", "y": y0})
    return records


@pytest.mark.parametrize("complete", [True, False])
def test_separation_is_reported_not_raised(complete: bool) -> None:
    design = build_design(separated_records(complete), Formula("y", ("A", "B"), group="task"))
    check = detect_separation(design)
    assert check.separated and "A[T.a1]" in check.terms
    for fit in (fit_logistic(design), fit_glmm(design)):
        assert fit.separation and not fit.converged
        assert "A[T.a1]" in fit.separated_terms
        assert any("separation" in w for w in fit.warnings)
        assert fit.coef[fit.index("A[T.a1]")] > 5


def test_no_separation_in_ordinary_data(clustered: Design) -> None:
    check = detect_separation(clustered)
    assert not check.separated and check.terms == ()
    assert check.direction == (0.0,) * clustered.n_params


def test_all_zero_response_is_separation() -> None:
    design = Design(x=np.ones((6, 1)), y=np.zeros(6), column_names=("(Intercept)",))
    fit = fit_logistic(design)
    assert fit.separation and fit.separated_terms == ("(Intercept)",)
    assert fit.coef[0] < -5 and not fit.converged


def test_failed_separation_check_is_a_warning(
    unclustered: Design, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failed:
        status = 4
        message = "numerical difficulties"
        x = None
        fun = None

    monkeypatch.setattr(glmm, "linprog", lambda *a, **k: Failed())
    check = detect_separation(unclustered)
    assert not check.checked and not check.separated
    fit = fit_logistic(unclustered)
    assert any("separation check failed" in w for w in fit.warnings)


def uniform_tasks() -> Design:
    """SYNTHETIC: each task's outcomes are all 0 or all 1, balanced over A and B."""
    records = [
        {"task": t, "A": f"a{i % 2}", "B": f"b{i % 3}", "y": t % 2}
        for t in range(10)
        for i in range(6)
    ]
    return build_design(records, Formula("y", ("A", "B"), group="task"))


@pytest.mark.parametrize("n_agq", [1, 8])
def test_sd_not_identified_when_every_task_is_uniform(n_agq: int) -> None:
    # The exact likelihood rises towards its supremum as the SD grows without bound;
    # few-node AGQ even shows a spurious maximum here, so this must be caught directly.
    design = uniform_tasks()
    assert not detect_separation(design).separated
    fit = fit_glmm(design, n_agq=n_agq)
    assert not fit.converged
    assert any("not identified" in w for w in fit.warnings)


def test_sd_at_the_limit_is_reported() -> None:
    fit = fit_glmm(uniform_tasks(), n_agq=25)
    assert not fit.converged
    assert fit.random_sd is not None and fit.random_sd >= SD_LIMIT
    assert any(f"limit {SD_LIMIT:g}" in w for w in fit.warnings)


def test_quadrature_check_flags_inaccurate_laplace_fits() -> None:
    # SYNTHETIC: small clusters and a large SD, where Laplace is least accurate.
    design = synthetic_design(seed=21, n_tasks=40, runs_per_task=8, coef=TRUE_COEF, sd=1.5)
    laplace = fit_glmm(design, n_agq=1)
    assert laplace.converged
    assert laplace.quadrature_shift is not None and laplace.quadrature_shift > QUADRATURE_TOL
    assert any(w.startswith("quadrature") for w in laplace.warnings)
    accurate = fit_glmm(design, n_agq=12)
    assert accurate.quadrature_shift is not None and accurate.quadrature_shift < 1e-4
    assert accurate.warnings == ()
    reference = fit_glmm(design, n_agq=CHECK_AGQ)
    assert reference.quadrature_shift is None
    assert reference.coef == pytest.approx(accurate.coef, abs=1e-4)


def test_quadrature_check_ignores_an_unfinished_optimisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SYNTHETIC: the design above, where 12 nodes are accurate. Stopping the optimiser
    # after one iteration leaves a large score, which is not a quadrature error.
    design = synthetic_design(seed=21, n_tasks=40, runs_per_task=8, coef=TRUE_COEF, sd=1.5)
    monkeypatch.setattr(glmm, "_NEWTON_REFINEMENTS", 0)
    fit = fit_glmm(design, n_agq=12, max_iter=1)
    assert not fit.converged and fit.random_sd is not None
    assert any("did not reach a converged maximum" in w for w in fit.warnings)
    assert np.max(np.abs(marginal_score(design, fit.coef, fit.random_sd, 12))) > 1.0
    assert fit.quadrature_shift is not None and fit.quadrature_shift < 1e-3
    assert not any(w.startswith("quadrature") for w in fit.warnings)


def test_quadrature_check_is_skipped_for_separated_designs() -> None:
    # SYNTHETIC: arm "small" never has an event; and an all-zero response in 4 tasks.
    arm = build_design(separated_arm_records(), Formula("y", ("arm", "M1"), group="task"))
    zeros = Design(
        x=np.ones((12, 1)),
        y=np.zeros(12),
        column_names=("(Intercept)",),
        groups=np.repeat(np.arange(4), 3),
    )
    for design in (arm, zeros):
        for n_agq in (1, 8):
            fit = fit_glmm(design, n_agq=n_agq)
            assert fit.separation and not fit.converged
            assert fit.quadrature_shift is None
            assert not any(w.startswith("quadrature") for w in fit.warnings)


def test_singular_information_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(glmm, "_inverse_pd", lambda matrix: None)
    monkeypatch.setattr(glmm, "_solve_pd", lambda matrix, vector: None)
    fit = fit_logistic(two_by_two())
    assert not fit.converged
    assert np.all(np.isnan(fit.se))
    assert any("not positive definite" in w for w in fit.warnings)


# Likelihood-ratio tests -------------------------------------------------------------


def test_lrt_for_the_random_intercept(clustered: Design, unclustered: Design) -> None:
    strong = likelihood_ratio_test(fit_logistic(clustered), fit_glmm(clustered))
    assert strong.boundary and strong.df == 1
    assert strong.statistic > 50 and strong.p_value < 1e-10
    assert strong.p_value == pytest.approx(0.5 * chi2.sf(strong.statistic, 1))
    weak = likelihood_ratio_test(fit_logistic(unclustered), fit_glmm(unclustered))
    assert weak.p_value > 0.01
    plain = likelihood_ratio_test(fit_logistic(unclustered), fit_glmm(unclustered), boundary=False)
    assert plain.p_value == pytest.approx(min(1.0, 2 * weak.p_value))


def test_lrt_for_nested_fixed_effects(clustered: Design) -> None:
    keep = [0, 1]
    reduced = Design(
        x=clustered.x[:, keep],
        y=clustered.y,
        column_names=tuple(clustered.column_names[j] for j in keep),
        groups=clustered.groups,
    )
    small_fit, big_fit = fit_logistic(reduced), fit_logistic(clustered)
    test = likelihood_ratio_test(small_fit, big_fit)
    assert test.df == 2 and not test.boundary
    stat = 2 * (big_fit.log_likelihood - small_fit.log_likelihood)
    assert test.statistic == pytest.approx(stat)
    assert test.p_value == pytest.approx(chi2.sf(stat, 2))
    mixed = likelihood_ratio_test(fit_logistic(reduced), fit_glmm(clustered))
    assert mixed.boundary and mixed.df == 3
    assert mixed.p_value == pytest.approx(
        0.5 * chi2.sf(mixed.statistic, 2) + 0.5 * chi2.sf(mixed.statistic, 3)
    )
    as_glmm = replace(big_fit, model="glmm", random_sd=0.0, n_groups=80, n_agq=1)
    zero = likelihood_ratio_test(big_fit, as_glmm)
    assert zero.boundary and zero.statistic == 0.0 and zero.p_value == 1.0
    # Two mixed models are comparable only under the same quadrature.
    small_glmm = replace(small_fit, model="glmm", random_sd=0.5, n_groups=80, n_agq=1)
    big_glmm = replace(big_fit, model="glmm", random_sd=0.5, n_groups=80, n_agq=8)
    with pytest.raises(ValueError, match="n_agq"):
        likelihood_ratio_test(small_glmm, big_glmm)
    same = likelihood_ratio_test(small_glmm, replace(big_glmm, n_agq=1))
    assert same.df == 2 and not same.boundary


def test_lrt_rejects_non_nested_models(clustered: Design, unclustered: Design) -> None:
    a = fit_logistic(clustered)
    with pytest.raises(ValueError, match="same data"):
        likelihood_ratio_test(a, fit_glmm(unclustered))
    with pytest.raises(ValueError, match="nested"):
        likelihood_ratio_test(fit_glmm(clustered), a)
    with pytest.raises(ValueError, match="more parameters"):
        likelihood_ratio_test(a, a)
    renamed = replace(a, column_names=("q", *a.column_names[1:]))
    with pytest.raises(ValueError, match="nested"):
        likelihood_ratio_test(renamed, fit_glmm(clustered))


def test_logistic_newton_handles_iteration_cap() -> None:
    fit = fit_logistic(two_by_two(), max_iter=1)
    assert not fit.converged
    assert fit.iterations == 1
    assert np.all(expit(fit.coef) > 0)


# Numerical safety paths -------------------------------------------------------------


def test_ascend_halves_overshooting_steps() -> None:
    def f(b: FloatArray) -> float:
        return -float((b[0] - 1.0) ** 2)

    found = glmm._ascend(f, np.zeros(1), f(np.zeros(1)), np.array([10.0]))
    assert found is not None
    point, value = found
    assert point[0] == pytest.approx(1.25) and value >= f(np.zeros(1))
    assert glmm._ascend(f, np.ones(1), 0.0, np.array([1.0])) is None


def test_solve_pd_rejects_non_finite_and_indefinite_matrices() -> None:
    assert glmm._solve_pd(np.array([[np.nan]]), np.ones(1)) is None
    assert glmm._solve_pd(np.array([[1.0, 0.0], [0.0, -1.0]]), np.ones(2)) is None
    assert glmm._solve_pd(np.array([[4.0]]), np.array([2.0])) == pytest.approx([0.5])


def test_logistic_reports_a_failed_line_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(glmm, "_ascend", lambda *args: None)
    fit = fit_logistic(two_by_two())
    assert not fit.converged and fit.iterations == 1
    assert any("did not converge" in w for w in fit.warnings)


def test_boundary_hessian_falls_back_to_the_fixed_effect_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SYNTHETIC: identical tasks, so the SD estimate is 0 (as in the exact test above).
    records = [
        {"task": task, "A": a, "y": int(i < (1 if a == "a0" else 3))}
        for task in range(8)
        for a in ("a0", "a1")
        for i in range(4)
    ]
    design = build_design(records, Formula("y", ("A",), group="task"))
    real = glmm._fd_hessian

    def flat_in_sd(objective: glmm.Objective, theta: FloatArray) -> FloatArray:
        hessian = real(objective, theta).copy()
        hessian[-1, :] = 0.0
        hessian[:, -1] = 0.0
        return hessian

    monkeypatch.setattr(glmm, "_fd_hessian", flat_in_sd)
    fit = fit_glmm(design)
    assert fit.converged and fit.quadrature_shift is None
    assert any("treat the random-intercept SD as known" in w for w in fit.warnings)
    assert fit.se == pytest.approx(fit_logistic(design).se, rel=1e-3)


def test_unfinished_optimisation_is_reported(
    clustered: Design, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(glmm, "_NEWTON_REFINEMENTS", 0)
    fit = fit_glmm(clustered, max_iter=1)
    assert not fit.converged
    assert any("did not reach a converged maximum" in w for w in fit.warnings)


def test_negative_sd_after_refinement_is_reflected(
    clustered: Design, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = fit_glmm(clustered, n_agq=3)
    real = glmm._refine

    def mirrored(
        objective: glmm.Objective, theta: FloatArray
    ) -> tuple[FloatArray, FloatArray, FloatArray, int]:
        # The same optimum seen at -sd: the likelihood is even in sd.
        point, grad, hessian, steps = real(objective, theta)
        point, grad, hessian = point.copy(), grad.copy(), hessian.copy()
        point[-1], grad[-1] = -point[-1], -grad[-1]
        hessian[-1, :-1] *= -1.0
        hessian[:-1, -1] *= -1.0
        return point, grad, hessian, steps

    monkeypatch.setattr(glmm, "_refine", mirrored)
    fit = fit_glmm(clustered, n_agq=3)
    assert fit.random_sd == pytest.approx(baseline.random_sd, abs=1e-12)
    assert fit.coef == pytest.approx(baseline.coef, abs=1e-12)
    assert fit.cov == pytest.approx(baseline.cov, rel=1e-9)
    assert fit.converged == baseline.converged
    assert baseline.quadrature_shift is not None
    assert fit.quadrature_shift == pytest.approx(baseline.quadrature_shift, rel=1e-6)


def test_fit_result_validates_shapes_and_freezes_arrays() -> None:
    fit = FitResult(
        model="logistic",
        column_names=("a", "b"),
        coef=[0.5, -1.0],  # type: ignore[arg-type]  # lists are accepted and converted
        cov=np.eye(2),
        random_sd=None,
        log_likelihood=-3.0,
        n_obs=10,
        n_events=4,
        n_groups=None,
        n_agq=None,
        converged=True,
        separation=False,
        separated_terms=(),
        warnings=(),
        iterations=1,
    )
    assert isinstance(fit.coef, np.ndarray) and not fit.coef.flags.writeable
    assert fit.se == pytest.approx([1.0, 1.0])
    with pytest.raises(ValueError, match="column names"):
        replace(fit, cov=np.eye(3))


def test_fit_results_compare_and_hash_by_value(unclustered: Design) -> None:
    first, second = fit_logistic(unclustered), fit_logistic(unclustered)
    assert first == second and hash(first) == hash(second)
    assert first != replace(first, coef=first.coef + 1e-12)
    mixed = fit_glmm(unclustered)
    assert mixed == fit_glmm(unclustered) and first != mixed
    assert first.__eq__(first.as_dict()) is NotImplemented
    # A failed fit's NaN covariance equals itself, and -0.0 equals 0.0, as values.
    failed = replace(first, cov=np.full_like(first.cov, np.nan), log_likelihood=math.nan)
    again = replace(first, cov=np.full_like(first.cov, np.nan), log_likelihood=float("nan"))
    assert failed == again and hash(failed) == hash(again)
    zero = replace(first, coef=np.zeros(first.coef.size))
    negative_zero = replace(first, coef=-np.zeros(first.coef.size))
    assert zero == negative_zero and hash(zero) == hash(negative_zero)
    assert len({first, second, failed, again}) == 2


def test_standard_errors_are_calibrated_across_replications() -> None:
    # 60 SYNTHETIC replications of one design: (estimate - truth) / SE should have
    # mean about 0 (SE of the mean 0.13) and SD about 1 (SE of the SD about 0.09).
    truth = np.array([TRUE_COEF[c] for c in COLUMNS])
    z = np.array(
        [
            (fit.coef - truth) / fit.se
            for fit in (
                fit_glmm(synthetic_design(seed, 40, 15, TRUE_COEF, 0.9), n_agq=4)
                for seed in range(1000, 1060)
            )
        ]
    )
    assert np.all(np.abs(z.mean(axis=0)) < 0.45)
    assert np.all((z.std(axis=0, ddof=1) > 0.7) & (z.std(axis=0, ddof=1) < 1.3))
