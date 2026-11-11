"""Linear contrasts of fitted coefficients, odds ratios, joint Wald tests, Holm adjustment.

A contrast is a weighted sum ``L' beta`` of the fixed effects of a
:class:`~receipts.analysis.glmm.FitResult`. Its estimate is ``L' beta_hat`` and its
variance ``L' Cov(beta_hat) L``, using the fit's covariance (the observed
information for ``fit_glmm`` and ``fit_logistic``). Tests and intervals are Wald
(normal) ones, so a contrast that picks out one coefficient reproduces that
coefficient's z, p-value, and interval. Odds ratios are ``exp`` of the estimate and
of the interval bounds on the log-odds scale. A value whose ``exp`` exceeds the
float range is ``inf``, never an exception: a separated fit (see
:func:`receipts.analysis.glmm.detect_separation`) has finite but huge standard errors,
so its odds-ratio interval is typically ``(0, inf)``.

:func:`wald_test` tests several contrasts jointly (chi-square with one degree of
freedom per row). :func:`holm_bonferroni` adjusts a family of p-values by Holm's
step-down procedure: with the p-values sorted ascending, the adjusted value of the
i-th (1-based) is the running maximum of ``(m - i + 1) * p_(i)``, capped at 1, and a
hypothesis is rejected when its adjusted value is at most ``alpha``. This rejects
exactly the hypotheses that the step-down rule ``p_(i) <= alpha / (m - i + 1)``,
applied until the first failure, rejects.

A fit whose covariance is NaN (singular information) gives NaN standard errors,
tests, and intervals rather than an exception. So does a contrast whose variance
``L' Cov L`` is not positive (a degenerate covariance), and a joint test whose
``L Cov L'`` is not positive definite.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import chi2, norm

from receipts.analysis.glmm import FitResult

FloatArray = NDArray[np.float64]
Weights = Mapping[str, float] | Sequence[float]

_SINGULAR_TOL = 1e-12


def _check_level(level: float) -> float:
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1), got {level}")
    return float(level)


def contrast_vector(fit: FitResult, weights: Weights) -> FloatArray:
    """Contrast weights as a vector over ``fit.column_names``.

    Args:
        fit: The fitted model.
        weights: Either a mapping from column name to weight (other columns get 0) or
            one weight per column, in column order.

    Raises:
        ValueError: A name is unknown, the length is wrong, a weight is not finite, or
            every weight is zero.
    """
    k = len(fit.column_names)
    if isinstance(weights, Mapping):
        unknown = [name for name in weights if name not in fit.column_names]
        if unknown:
            raise ValueError("unknown column(s) in contrast: " + ", ".join(map(str, unknown)))
        vector = np.zeros(k)
        for name, w in weights.items():
            vector[fit.index(name)] = float(w)
    else:
        vector = np.array([float(w) for w in weights], dtype=np.float64)
        if vector.shape != (k,):
            raise ValueError(f"expected {k} weights (one per column), got {vector.size}")
    if not np.all(np.isfinite(vector)):
        raise ValueError("contrast weights must be finite")
    if not np.any(vector):
        raise ValueError("a contrast needs at least one nonzero weight")
    return vector


def _exp(value: float) -> float:
    """``exp(value)``, with ``inf`` instead of OverflowError (NaN stays NaN)."""
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _label(fit: FitResult, vector: FloatArray) -> str:
    return " + ".join(
        f"{w:g}*{name}" for name, w in zip(fit.column_names, vector, strict=True) if w
    )


@dataclass(frozen=True)
class Contrast:
    """A linear contrast ``L' beta`` with its Wald test and interval.

    Attributes:
        name: Label of the contrast.
        weights: The contrast vector ``L`` over the fit's columns.
        estimate: ``L' beta_hat`` on the log-odds scale.
        se: Standard error, ``sqrt(L' Cov L)``.
        z: Wald statistic ``estimate / se``.
        p_value: Two-sided normal p-value.
        ci_low: Lower bound of the Wald interval.
        ci_high: Upper bound of the Wald interval.
        level: Coverage level of the interval.
    """

    name: str
    weights: tuple[float, ...]
    estimate: float
    se: float
    z: float
    p_value: float
    ci_low: float
    ci_high: float
    level: float

    @property
    def odds_ratio(self) -> float:
        """``exp(estimate)``: the odds ratio the contrast describes (``inf`` on overflow)."""
        return _exp(self.estimate)

    @property
    def or_ci_low(self) -> float:
        """Lower bound of the odds-ratio interval, ``exp(ci_low)`` (``inf`` on overflow)."""
        return _exp(self.ci_low)

    @property
    def or_ci_high(self) -> float:
        """Upper bound of the odds-ratio interval, ``exp(ci_high)`` (``inf`` on overflow)."""
        return _exp(self.ci_high)

    def as_dict(self) -> dict[str, Any]:
        """Mapping of every field plus the odds ratio and its interval, for JSON.

        Values are plain floats and can be NaN or ``inf`` (a failed or separated fit),
        which ``json.dumps`` writes as ``NaN`` and ``Infinity`` unless ``allow_nan`` is
        False.
        """
        out = asdict(self)
        out["weights"] = list(self.weights)
        out.update(odds_ratio=self.odds_ratio, or_ci_low=self.or_ci_low, or_ci_high=self.or_ci_high)
        return out


def linear_contrast(
    fit: FitResult, weights: Weights, name: str = "", level: float | None = None
) -> Contrast:
    """Estimate, SE, Wald z and p-value, and interval of a linear contrast.

    Args:
        fit: The fitted model.
        weights: See :func:`contrast_vector`.
        name: Label; defaults to the nonzero weights, e.g. ``"1*M1 + -1*M2"``.
        level: Interval coverage level; defaults to the fit's level.
    """
    level = _check_level(fit.level if level is None else level)
    vector = contrast_vector(fit, weights)
    estimate = float(vector @ fit.coef)
    variance = float(vector @ fit.cov @ vector)
    se = math.sqrt(variance) if variance > 0.0 else math.nan
    z = estimate / se if variance > 0.0 else math.nan
    p_value = float(2.0 * norm.sf(abs(z)))
    half = float(norm.ppf(0.5 + level / 2.0)) * se
    return Contrast(
        name=name or _label(fit, vector),
        weights=tuple(float(w) for w in vector),
        estimate=estimate,
        se=se,
        z=z,
        p_value=p_value,
        ci_low=estimate - half,
        ci_high=estimate + half,
        level=level,
    )


def odds_ratio(fit: FitResult, term: str, level: float | None = None) -> Contrast:
    """The contrast for one coefficient; its ``odds_ratio`` is ``exp`` of the estimate."""
    return linear_contrast(fit, {term: 1.0}, name=term, level=level)


@dataclass(frozen=True)
class WaldTest:
    """A joint Wald test that several contrasts are all zero.

    Attributes:
        statistic: ``(L b)' (L Cov L')^-1 (L b)``.
        df: Number of contrasts (rows of ``L``).
        p_value: Upper tail of chi-square with ``df`` degrees of freedom.
    """

    statistic: float
    df: int
    p_value: float


def wald_test(fit: FitResult, rows: Sequence[Weights]) -> WaldTest:
    """Joint Wald chi-square test of ``L beta = 0`` for the given contrast rows.

    The statistic and p-value are NaN when ``L Cov L'`` is not positive definite
    (a failed fit or a degenerate covariance).

    Raises:
        ValueError: No rows, a bad row (see :func:`contrast_vector`), or linearly
            dependent rows.
    """
    if not rows:
        raise ValueError("a Wald test needs at least one contrast row")
    matrix = np.vstack([contrast_vector(fit, row) for row in rows])
    if np.linalg.matrix_rank(matrix) < matrix.shape[0]:
        raise ValueError("the contrast rows must be linearly independent")
    df = int(matrix.shape[0])
    values = matrix @ fit.coef
    variance = matrix @ fit.cov @ matrix.T
    if not _positive_definite(variance):
        return WaldTest(statistic=math.nan, df=df, p_value=math.nan)
    statistic = float(values @ np.linalg.solve(variance, values))
    return WaldTest(statistic=statistic, df=df, p_value=float(chi2.sf(statistic, df)))


def _positive_definite(matrix: FloatArray) -> bool:
    """True when a symmetric matrix is finite and its smallest eigenvalue is clearly > 0.

    "Clearly" means above ``_SINGULAR_TOL`` times the largest eigenvalue, so a matrix
    that is singular up to rounding error counts as singular.
    """
    if not np.all(np.isfinite(matrix)):
        return False
    eigenvalues = np.linalg.eigvalsh(0.5 * (matrix + matrix.T))
    return bool(eigenvalues[-1] > 0.0 and eigenvalues[0] > _SINGULAR_TOL * eigenvalues[-1])


@dataclass(frozen=True)
class HolmResult:
    """Holm-Bonferroni adjusted p-values for a family of hypotheses (input order).

    Attributes:
        p_values: The unadjusted p-values.
        adjusted: Holm-adjusted p-values.
        reject: Whether each hypothesis is rejected at familywise level ``alpha``.
        alpha: Familywise error rate.
    """

    p_values: tuple[float, ...]
    adjusted: tuple[float, ...]
    reject: tuple[bool, ...]
    alpha: float

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready mapping with the method name."""
        return {
            "method": "holm-bonferroni",
            "alpha": self.alpha,
            "p_values": list(self.p_values),
            "adjusted": list(self.adjusted),
            "reject": list(self.reject),
        }


def holm_bonferroni(p_values: Sequence[float], alpha: float = 0.05) -> HolmResult:
    """Holm's step-down adjustment (see the module docstring).

    Raises:
        ValueError: A p-value is NaN or outside ``[0, 1]``, or ``alpha`` is outside ``(0, 1)``.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    p = np.array([float(v) for v in p_values], dtype=np.float64)
    if np.any(np.isnan(p)) or np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("p-values must be numbers in [0, 1]")
    m = p.size
    order = np.argsort(p, kind="stable")
    stepped = np.maximum.accumulate((m - np.arange(m)) * p[order])
    adjusted = np.empty(m)
    adjusted[order] = np.minimum(stepped, 1.0)
    return HolmResult(
        p_values=tuple(float(v) for v in p),
        adjusted=tuple(float(v) for v in adjusted),
        reject=tuple(bool(v <= alpha) for v in adjusted),
        alpha=float(alpha),
    )
