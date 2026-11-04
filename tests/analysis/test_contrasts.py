"""Tests for receipts.analysis.contrasts.

The fits below are either built by hand with made-up numbers (labeled) or fitted
to SYNTHETIC data from tests/analysis/synthetic.py.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from scipy.stats import chi2, norm

from receipts.analysis.contrasts import (
    Contrast,
    HolmResult,
    WaldTest,
    contrast_vector,
    holm_bonferroni,
    linear_contrast,
    odds_ratio,
    wald_test,
)
from receipts.analysis.design import INTERCEPT, Design, Formula, build_design
from receipts.analysis.glmm import FitResult, fit_glmm, fit_logistic
from tests.analysis.synthetic import TRUE_COEF, separated_arm_records, synthetic_design


def hand_fit(cov: Any = None) -> FitResult:
    """A FitResult with made-up estimates and covariance (not fitted to anything)."""
    return FitResult(
        model="logistic",
        column_names=("(Intercept)", "M1", "M2"),
        coef=np.array([-1.0, 0.8, 0.3]),
        cov=np.array([[0.04, -0.01, -0.01], [-0.01, 0.09, 0.02], [-0.01, 0.02, 0.16]])
        if cov is None
        else cov,
        random_sd=None,
        log_likelihood=-50.0,
        n_obs=100,
        n_events=30,
        n_groups=None,
        n_agq=None,
        converged=True,
        separation=False,
        separated_terms=(),
        warnings=(),
        iterations=5,
    )


# Contrasts ---------------------------------------------------------------------------


def test_contrast_vector_from_names_and_sequences() -> None:
    fit = hand_fit()
    assert contrast_vector(fit, {"M1": 1.0, "M2": -1.0}).tolist() == [0.0, 1.0, -1.0]
    assert contrast_vector(fit, [0, 2, 0]).tolist() == [0.0, 2.0, 0.0]
    with pytest.raises(ValueError, match="unknown"):
        contrast_vector(fit, {"M9": 1.0})
    with pytest.raises(ValueError, match="3 weights"):
        contrast_vector(fit, [1.0, 2.0])
    with pytest.raises(ValueError, match="finite"):
        contrast_vector(fit, [1.0, math.nan, 0.0])
    with pytest.raises(ValueError, match="nonzero"):
        contrast_vector(fit, {"M1": 0.0})


def test_difference_contrast_matches_hand_computation() -> None:
    fit = hand_fit()
    c = linear_contrast(fit, {"M1": 1.0, "M2": -1.0}, name="M1 - M2")
    # Hand-computed: estimate 0.8 - 0.3; variance 0.09 + 0.16 - 2 * 0.02 = 0.21.
    se = math.sqrt(0.21)
    assert isinstance(c, Contrast)
    assert c.name == "M1 - M2" and c.weights == (0.0, 1.0, -1.0)
    assert c.estimate == pytest.approx(0.5)
    assert c.se == pytest.approx(se)
    assert c.z == pytest.approx(0.5 / se)
    assert c.p_value == pytest.approx(2 * norm.sf(0.5 / se))
    assert (c.ci_low, c.ci_high) == pytest.approx(
        (0.5 - 1.959963984540054 * se, 0.5 + 1.959963984540054 * se)
    )
    assert c.odds_ratio == pytest.approx(math.exp(0.5))
    assert (c.or_ci_low, c.or_ci_high) == pytest.approx((math.exp(c.ci_low), math.exp(c.ci_high)))
    assert c.level == 0.95


def test_contrast_level_and_default_name() -> None:
    c = linear_contrast(hand_fit(), [0.0, 1.0, 1.0], level=0.9)
    se = math.sqrt(0.09 + 0.16 + 2 * 0.02)
    assert c.ci_high - c.estimate == pytest.approx(norm.ppf(0.95) * se)
    assert c.name == "1*M1 + 1*M2"
    with pytest.raises(ValueError, match="level"):
        linear_contrast(hand_fit(), [0.0, 1.0, 0.0], level=0.0)


def test_single_coefficient_contrast_reproduces_the_fit() -> None:
    design = synthetic_design(seed=2, n_tasks=30, runs_per_task=12, coef=TRUE_COEF, sd=0.8)
    fit = fit_glmm(design)
    c = odds_ratio(fit, "A[T.a1]")
    coefficient = fit.coefficient("A[T.a1]")
    assert c.name == "A[T.a1]"
    assert c.estimate == pytest.approx(coefficient.estimate)
    assert c.se == pytest.approx(coefficient.se)
    assert c.p_value == pytest.approx(coefficient.p_value)
    assert (c.ci_low, c.ci_high) == pytest.approx((coefficient.ci_low, coefficient.ci_high))
    assert c.odds_ratio == pytest.approx(math.exp(coefficient.estimate))


def test_contrast_as_dict() -> None:
    c = odds_ratio(hand_fit(), "M2")
    out = c.as_dict()
    assert out["name"] == "M2" and out["weights"] == [0.0, 0.0, 1.0]
    assert out["odds_ratio"] == c.odds_ratio
    assert out["or_ci_low"] == c.or_ci_low and out["or_ci_high"] == c.or_ci_high
    assert {"estimate", "se", "z", "p_value", "ci_low", "ci_high", "level"} <= set(out)


def test_contrast_on_a_failed_fit_is_nan_not_an_error() -> None:
    c = linear_contrast(hand_fit(cov=np.full((3, 3), np.nan)), {"M1": 1.0})
    assert c.estimate == pytest.approx(0.8)
    assert math.isnan(c.se) and math.isnan(c.p_value) and math.isnan(c.or_ci_low)
    assert math.isnan(c.or_ci_high) and c.odds_ratio == pytest.approx(math.exp(0.8))


def test_odds_ratio_of_a_separated_fit_is_inf_not_an_error() -> None:
    # Separation leaves the estimate finite but its SE huge, so exp(ci_high) is beyond
    # the float range: the bound is inf and as_dict() still works.
    design = build_design(separated_arm_records(), Formula("y", ("arm", "M1"), group="task"))
    for fit in (fit_glmm(design, n_agq=8), fit_logistic(design)):
        assert fit.separation and "arm[T.small]" in fit.separated_terms
        c = odds_ratio(fit, "arm[T.small]")
        assert math.isfinite(c.se) and c.se > 1e3 and c.ci_high > 710.0
        out = c.as_dict()
        assert out["or_ci_high"] == math.inf and out["or_ci_low"] == 0.0
        assert 0.0 <= out["odds_ratio"] < 1e-6
    # An all-zero response is separated in the intercept alone.
    zeros = fit_logistic(Design(x=np.ones((6, 1)), y=np.zeros(6), column_names=(INTERCEPT,)))
    assert odds_ratio(zeros, INTERCEPT).as_dict()["or_ci_high"] == math.inf


def test_odds_ratio_bounds_overflow_to_inf() -> None:
    # Made-up contrast values beyond exp's float range (about 709.78).
    c = Contrast("x", (1.0,), 800.0, 1.0, 800.0, 0.0, 798.0, 802.0, 0.95)
    assert c.odds_ratio == math.inf and c.or_ci_low == math.inf and c.or_ci_high == math.inf
    low = Contrast("x", (1.0,), -800.0, math.nan, math.nan, math.nan, -math.inf, math.nan, 0.95)
    assert low.odds_ratio == 0.0 and low.or_ci_low == 0.0 and math.isnan(low.or_ci_high)


def test_contrast_with_zero_variance_is_nan_not_an_error() -> None:
    # Made-up degenerate covariance: M1 has variance 0, so its SE is not usable.
    cov = np.diag([0.04, 0.0, 0.16])
    c = linear_contrast(hand_fit(cov=cov), {"M1": 1.0})
    assert c.estimate == pytest.approx(0.8)
    assert math.isnan(c.se) and math.isnan(c.z) and math.isnan(c.p_value)
    assert math.isnan(c.ci_low) and math.isnan(c.ci_high)
    # Rounding can make the variance of a contrast slightly negative: also NaN.
    tiny = linear_contrast(hand_fit(cov=np.diag([0.04, -1e-18, 0.16])), {"M1": 1.0})
    assert math.isnan(tiny.se)


# Joint Wald tests ----------------------------------------------------------------------


def test_wald_test_single_row_is_z_squared() -> None:
    fit = hand_fit()
    test = wald_test(fit, [{"M1": 1.0}])
    z = 0.8 / 0.3
    assert isinstance(test, WaldTest)
    assert test.df == 1
    assert test.statistic == pytest.approx(z * z)
    assert test.p_value == pytest.approx(2 * norm.sf(z))


def test_wald_test_two_rows_matches_matrix_formula() -> None:
    fit = hand_fit()
    test = wald_test(fit, [{"M1": 1.0}, [0.0, 0.0, 1.0]])
    b = np.array([0.8, 0.3])
    v = np.array([[0.09, 0.02], [0.02, 0.16]])
    stat = float(b @ np.linalg.solve(v, b))
    assert test.df == 2
    assert test.statistic == pytest.approx(stat)
    assert test.p_value == pytest.approx(chi2.sf(stat, 2))


def test_wald_test_rejects_dependent_or_empty_rows() -> None:
    fit = hand_fit()
    with pytest.raises(ValueError, match="linearly independent"):
        wald_test(fit, [{"M1": 1.0}, {"M1": 2.0}])
    with pytest.raises(ValueError, match="at least one"):
        wald_test(fit, [])


@pytest.mark.parametrize(
    "cov",
    [
        np.full((3, 3), np.nan),  # a failed fit
        np.array([[0.04, 0.0, 0.0], [0.0, 0.09, 0.09], [0.0, 0.09, 0.09]]),  # singular
        np.diag([0.04, 0.09, -0.01]),  # not positive semidefinite
    ],
)
def test_wald_test_with_unusable_covariance_is_nan(cov: Any) -> None:
    # Made-up covariances: independent rows whose L Cov L' is not positive definite.
    test = wald_test(hand_fit(cov=cov), [{"M1": 1.0}, {"M2": 1.0}])
    assert test.df == 2
    assert math.isnan(test.statistic) and math.isnan(test.p_value)


# Holm-Bonferroni -------------------------------------------------------------------------


def test_holm_matches_a_hand_computed_example() -> None:
    # Hand-computed: sorted p = 0.005, 0.01, 0.03, 0.04 times 4, 3, 2, 1 gives
    # 0.02, 0.03, 0.06, 0.04; the running maximum is 0.02, 0.03, 0.06, 0.06.
    result = holm_bonferroni([0.01, 0.04, 0.03, 0.005])
    assert isinstance(result, HolmResult)
    assert result.adjusted == pytest.approx((0.03, 0.06, 0.06, 0.02))
    assert result.reject == (True, False, False, True)
    assert result.p_values == (0.01, 0.04, 0.03, 0.005)
    assert result.alpha == 0.05


def test_holm_step_down_stops_at_the_first_non_rejection() -> None:
    # Hand-computed: thresholds alpha / 3, alpha / 2, alpha / 1 = 0.0167, 0.025, 0.05.
    # 0.02 fails the first threshold, so nothing is rejected, even 0.04 < 0.05.
    result = holm_bonferroni([0.02, 0.04, 0.03])
    assert result.reject == (False, False, False)
    assert result.adjusted == pytest.approx((0.06, 0.06, 0.06))


def test_holm_ties_caps_and_alpha() -> None:
    result = holm_bonferroni([0.01, 0.01, 0.5, 1.0], alpha=0.1)
    assert result.adjusted == pytest.approx((0.04, 0.04, 1.0, 1.0))
    assert result.reject == (True, True, False, False)
    assert holm_bonferroni([]).adjusted == ()


@pytest.mark.parametrize(
    ("p_values", "alpha"), [([0.1, math.nan], 0.05), ([-0.1], 0.05), ([1.5], 0.05), ([0.1], 0.0)]
)
def test_holm_rejects_bad_input(p_values: list[float], alpha: float) -> None:
    with pytest.raises(ValueError):
        holm_bonferroni(p_values, alpha=alpha)


def test_holm_as_dict() -> None:
    out = holm_bonferroni([0.01, 0.2]).as_dict()
    assert out == {
        "method": "holm-bonferroni",
        "alpha": 0.05,
        "p_values": [0.01, 0.2],
        "adjusted": [0.02, 0.2],
        "reject": [True, False],
    }
