"""Logistic regression with a random intercept per cluster (task), by maximum likelihood.

Model, for observation (run) j in cluster (task) i::

    y_ij ~ Bernoulli(p_ij),   logit(p_ij) = x_ij' beta + sd * u_i,   u_i ~ N(0, 1)

so the random intercept ``sd * u_i`` has standard deviation ``sd`` on the logit scale
and ``beta`` holds conditional (task-specific) effects. :func:`fit_logistic` fits the
same linear predictor without the random intercept.

Likelihood. Each cluster's marginal likelihood, the integral over ``u_i``, is
computed by adaptive Gauss-Hermite quadrature: the ``n_agq`` Gauss-Hermite nodes
(``numpy.polynomial.hermite_e.hermegauss``) are centred at the mode of the
cluster's integrand and scaled by the inverse square root of its curvature there.
``n_agq = 1`` is the Laplace approximation; more nodes converge to the exact
integral. The mode is found by Newton's method with step halving (the log integrand
is strictly concave in ``u_i``). At ``sd = 0`` the value is exactly the plain
logistic log-likelihood, and the value is an even function of ``sd``.

Fitting. :func:`fit_glmm` passes the log-likelihood and its exact gradient to
``scipy.optimize.minimize`` (BFGS), starting from the plain logistic estimates and
``sd = 1``. The gradient includes the dependence of the adaptive nodes on the
parameters (implicit differentiation of the mode condition). Because the
likelihood is even in ``sd``, ``sd`` is optimised without a bound and its absolute
value is reported, so an estimate on the boundary ``sd = 0`` is reachable. The BFGS
solution is refined by up to three Newton steps with a finite-difference Hessian
(central differences of the exact gradient). :func:`fit_logistic` uses Newton's
method with step halving.

Inference. The covariance of the fixed effects is the fixed-effect block of the
inverse observed information (the Hessian of minus the log-likelihood over all
parameters, fixed effects and ``sd``). If that Hessian is not positive definite but
its fixed-effect block is, the block alone is inverted and a warning says the SEs
treat ``sd`` as known; such a fit counts as converged only when ``sd`` is at or next
to 0 (below 1e-3), the boundary case. Wald ``z = estimate / SE``,
two-sided normal p-values, normal intervals at ``level`` (95 percent by default).
``AIC = -2 log L + 2 k``, where ``k`` counts the fixed effects plus one for ``sd``.

Convergence and failures. ``converged`` is True when the Hessian is positive
definite (or the boundary case above), the Newton step at the estimate is below
``STEP_TOL`` in every parameter, ``sd < SD_LIMIT``, the SD is identified, and the
design is not separated; for :func:`fit_logistic`, when the information matrix is
positive definite, the Newton step is below ``STEP_TOL``, and the design is not
separated. Separation (a combination of columns that
predicts the outcome perfectly, so no finite estimate exists) is detected before
fitting by a linear program; the fit still returns, with ``separation`` set,
``separated_terms`` naming the columns along a separating direction, a warning,
and ``converged`` False. When every cluster's outcomes are all equal the
SD is not identified (its estimate is infinite), and an ``sd`` at or beyond
``SD_LIMIT`` means such clusters push it towards infinity; both are warnings with
``converged`` False. Nothing here raises on separation or non-convergence.

Quadrature accuracy. AGQ with few nodes can be inaccurate when clusters are small
and the SD is large, and it can even show a spurious maximum when many clusters
have all-equal outcomes. :func:`fit_glmm` therefore compares, at the estimate, the
Newton step on the ``CHECK_AGQ``-node likelihood with the Newton step on the
``n_agq``-node likelihood (both with the ``n_agq`` Hessian ``H``), and reports the
largest difference in any parameter, ``max |H^-1 (score_CHECK_AGQ - score_n_agq)|``,
as ``quadrature_shift``, with a warning above ``QUADRATURE_TOL``. Taking the
difference keeps out of the measure the step that remains when the optimiser
stopped before the maximum, which has its own warning. The check is skipped for a
separated design: its estimates along the separating direction are not meaningful,
and its nearly singular Hessian would magnify rounding error.

Bootstrap. :func:`bootstrap_coefficients` gives cluster (task) bootstrap percentile
intervals for every coefficient by refitting the model on resampled tasks, with
each drawn copy of a task treated as its own cluster.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
from numpy.polynomial.hermite_e import hermegauss
from numpy.typing import ArrayLike, NDArray
from scipy.linalg import LinAlgError, cho_factor, cho_solve
from scipy.optimize import linprog, minimize
from scipy.special import expit, logsumexp
from scipy.stats import chi2, norm

from receipts.analysis._values import value_key
from receipts.analysis.design import Design, Formula, build_design
from receipts.analysis.rates import BootstrapResult, cluster_bootstrap_many, relabel_field

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.intp]
Objective = Callable[[FloatArray], tuple[float, FloatArray]]


def _floats(value: ArrayLike) -> FloatArray:
    """``value`` as a float64 array; a float64 array is returned unchanged, not copied.

    NumPy 2.5's type stubs (the lock resolves NumPy 2.5 for Python 3.12 and later) type
    some array expressions, such as a matrix-vector product, as scalars. Wrapping them
    keeps ``mypy --strict`` passing on every supported Python without changing a value.
    """
    return np.asarray(value, dtype=np.float64)


MAX_AGQ = 50
"""Largest supported number of quadrature nodes."""

SD_LIMIT = 25.0
"""A random-intercept SD at or above this (logit scale) is reported as diverging."""

STEP_TOL = 1e-5
"""Largest Newton step (in any parameter) at which a fit counts as converged."""

CHECK_AGQ = MAX_AGQ
"""Nodes of the reference likelihood used by the quadrature-accuracy check."""

QUADRATURE_TOL = 0.01
"""A ``quadrature_shift`` above this (log-odds or SD units) gives a warning."""

_LOG_2PI = math.log(2.0 * math.pi)
_MODE_TOL = 1e-10
_MODE_MAX_ITER = 100
_MAX_HALVINGS = 60
_SEPARATION_TOL = 1e-6
_FD_STEP = 1e-5
_NEWTON_REFINEMENTS = 3


# Helpers ------------------------------------------------------------------------------


def _check_level(level: float) -> float:
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1), got {level}")
    return float(level)


def _check_n_agq(n_agq: int) -> int:
    value = operator.index(n_agq)
    if not 1 <= value <= MAX_AGQ:
        raise ValueError(f"n_agq must be between 1 and {MAX_AGQ}, got {value}")
    return value


def _require_groups(design: Design) -> IntArray:
    if design.groups is None:
        raise ValueError("a random-intercept model needs a design with clusters (groups)")
    if design.n_groups < 2:
        raise ValueError("a random-intercept model needs at least two clusters")
    return design.groups


def _solve_pd(matrix: FloatArray, vector: FloatArray) -> FloatArray | None:
    """Solve ``matrix @ out = vector`` for a positive definite matrix; None if it is not."""
    if not np.all(np.isfinite(matrix)):
        return None
    try:
        factor = cho_factor(matrix)
    except LinAlgError:
        return None
    return np.asarray(cho_solve(factor, vector), dtype=np.float64)


def _inverse_pd(matrix: FloatArray) -> FloatArray | None:
    """Inverse of a positive definite matrix, or None if it is not positive definite."""
    return _solve_pd(matrix, np.eye(matrix.shape[0]))


def _softplus(eta: FloatArray) -> FloatArray:
    return np.logaddexp(0.0, eta)


# Separation -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SeparationCheck:
    """Result of the linear-programming check for (quasi-)complete separation.

    Attributes:
        separated: True when some direction ``d`` has ``(2 y_i - 1) x_i' d >= 0`` for
            every observation and ``> 0`` for at least one, so the likelihood keeps
            rising along ``d`` and no finite maximum exists.
        terms: Column names with a nonzero weight in the direction found.
        direction: The direction found (each weight in ``[-1, 1]``), zeros if none.
        checked: False when the linear program failed, so separation is unknown.
        message: The solver's message when ``checked`` is False.
    """

    separated: bool
    terms: tuple[str, ...]
    direction: tuple[float, ...]
    checked: bool = True
    message: str = ""


def detect_separation(design: Design) -> SeparationCheck:
    """Check a design for complete or quasi-complete separation.

    Solves: maximise ``sum_i s_i x_i' d`` subject to ``s_i x_i' d >= 0`` for all ``i``
    and ``-1 <= d_j <= 1``, with ``s_i = 2 y_i - 1`` (scipy ``linprog``, HiGHS). A
    positive optimum means separation. A random intercept does not remove
    separation in the fixed effects, so the same check applies to :func:`fit_glmm`.
    """
    signs = 2.0 * design.y - 1.0
    margins = signs[:, None] * design.x
    zeros = (0.0,) * design.n_params
    result = linprog(
        c=-margins.sum(axis=0),
        A_ub=-margins,
        b_ub=np.zeros(design.n_obs),
        bounds=[(-1.0, 1.0)] * design.n_params,
        method="highs",
    )
    if result.status != 0 or result.x is None or result.fun is None:
        return SeparationCheck(False, (), zeros, checked=False, message=str(result.message))
    if -float(result.fun) <= _SEPARATION_TOL:
        return SeparationCheck(False, (), zeros)
    direction = np.where(np.abs(result.x) > 1e-9, np.asarray(result.x, dtype=np.float64), 0.0)
    terms = tuple(name for name, d in zip(design.column_names, direction, strict=True) if d)
    return SeparationCheck(True, terms, tuple(float(d) for d in direction))


def _separation_warnings(check: SeparationCheck) -> list[str]:
    if not check.checked:
        return [f"separation check failed: {check.message}"]
    if check.separated:
        return [
            "separation: no finite maximum likelihood estimate exists; estimates along the "
            "separating direction are not meaningful (" + ", ".join(check.terms) + ")"
        ]
    return []


# Results ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Coefficient:
    """One fixed effect with its Wald statistics.

    Attributes:
        name: Column name.
        estimate: Estimate on the log-odds scale.
        se: Standard error.
        z: Wald statistic ``estimate / se``.
        p_value: Two-sided normal p-value.
        ci_low: Lower bound of the Wald interval at the fit's level.
        ci_high: Upper bound of the Wald interval.
    """

    name: str
    estimate: float
    se: float
    z: float
    p_value: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True, eq=False)
class FitResult:
    """A fitted logistic model, with or without a random intercept.

    ``se``, ``z``, ``p_values``, ``ci_low``, ``ci_high``, ``n_params``, and ``aic`` are
    derived from the stored fields. Arrays are read-only. Fits compare and hash by
    value: two are equal when every field is (arrays element by element, NaN equal to
    NaN), so two fits of the same design in one environment compare equal.

    Attributes:
        model: ``"glmm"`` (random intercept) or ``"logistic"``.
        column_names: Fixed-effect names, in the order of ``coef``.
        coef: Fixed-effect estimates (log-odds scale).
        cov: Covariance of ``coef`` (NaN when the information is singular).
        random_sd: Random-intercept SD on the logit scale (None for ``logistic``).
        log_likelihood: Maximised log-likelihood (the AGQ approximation for ``glmm``).
        n_obs: Number of observations.
        n_events: Number of observations with ``y = 1``.
        n_groups: Number of clusters (None for ``logistic``).
        n_agq: Quadrature nodes per cluster (None for ``logistic``).
        converged: True when an interior maximum was found (module docstring).
        separation: True when the design is separated.
        separated_terms: Columns along the separating direction.
        warnings: Human-readable problems, empty for a clean fit.
        iterations: Optimiser iterations (BFGS plus Newton refinements, or Newton).
        level: Coverage level of the Wald intervals.
        quadrature_shift: For ``glmm`` with ``n_agq < CHECK_AGQ``: the largest
            difference, in any parameter, between the Newton steps on the
            ``CHECK_AGQ``-node and the ``n_agq``-node likelihoods from the estimate (a
            measure of quadrature error, see the module docstring); None when not
            computed (``logistic``, ``n_agq = CHECK_AGQ``, a Hessian that is not
            positive definite, or a separated design).
    """

    model: Literal["glmm", "logistic"]
    column_names: tuple[str, ...]
    coef: FloatArray
    cov: FloatArray
    random_sd: float | None
    log_likelihood: float
    n_obs: int
    n_events: int
    n_groups: int | None
    n_agq: int | None
    converged: bool
    separation: bool
    separated_terms: tuple[str, ...]
    warnings: tuple[str, ...]
    iterations: int
    level: float = 0.95
    quadrature_shift: float | None = None

    def __post_init__(self) -> None:
        coef = _frozen(self.coef)
        cov = _frozen(self.cov)
        k = len(self.column_names)
        if coef.shape != (k,) or cov.shape != (k, k):
            raise ValueError(
                f"{k} column names need coef of shape ({k},) and cov of shape ({k}, {k}); "
                f"got {coef.shape} and {cov.shape}"
            )
        object.__setattr__(self, "column_names", tuple(self.column_names))
        object.__setattr__(self, "coef", coef)
        object.__setattr__(self, "cov", cov)

    def __eq__(self, other: object) -> bool:
        """True when ``other`` is a FitResult with equal fields (arrays element by element)."""
        if type(other) is not type(self):
            return NotImplemented
        return value_key(self) == value_key(other)

    def __hash__(self) -> int:
        """Hash of the field values, consistent with ``==``."""
        return hash(value_key(self))

    @property
    def se(self) -> FloatArray:
        """Standard errors: square roots of the diagonal of ``cov``."""
        return np.sqrt(np.diag(self.cov))

    @property
    def z(self) -> FloatArray:
        """Wald z statistics."""
        return self.coef / self.se

    @property
    def p_values(self) -> FloatArray:
        """Two-sided p-values of the Wald z statistics."""
        return np.asarray(2.0 * norm.sf(np.abs(self.z)), dtype=np.float64)

    @property
    def _quantile(self) -> float:
        return float(norm.ppf(0.5 + self.level / 2.0))

    @property
    def ci_low(self) -> FloatArray:
        """Lower bounds of the Wald intervals."""
        return self.coef - self._quantile * self.se

    @property
    def ci_high(self) -> FloatArray:
        """Upper bounds of the Wald intervals."""
        return self.coef + self._quantile * self.se

    @property
    def n_params(self) -> int:
        """Number of estimated parameters: fixed effects, plus one SD for ``glmm``."""
        return len(self.column_names) + (1 if self.model == "glmm" else 0)

    @property
    def aic(self) -> float:
        """Akaike information criterion, ``-2 log L + 2 n_params``."""
        return -2.0 * self.log_likelihood + 2.0 * self.n_params

    def index(self, name: str) -> int:
        """Position of the column ``name``; raises KeyError if absent."""
        try:
            return self.column_names.index(name)
        except ValueError:
            raise KeyError(name) from None

    def coefficient(self, name: str) -> Coefficient:
        """Wald statistics of one fixed effect."""
        j = self.index(name)
        return Coefficient(
            name=name,
            estimate=float(self.coef[j]),
            se=float(self.se[j]),
            z=float(self.z[j]),
            p_value=float(self.p_values[j]),
            ci_low=float(self.ci_low[j]),
            ci_high=float(self.ci_high[j]),
        )

    def table(self) -> list[Coefficient]:
        """Every fixed effect, in column order."""
        return [self.coefficient(name) for name in self.column_names]

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready summary, including the covariance matrix (for later contrasts)."""
        return {
            "model": self.model,
            "terms": [vars(c) for c in self.table()],
            "cov": self.cov.tolist(),
            "random_sd": self.random_sd,
            "log_likelihood": self.log_likelihood,
            "aic": self.aic,
            "n_params": self.n_params,
            "n_obs": self.n_obs,
            "n_events": self.n_events,
            "n_groups": self.n_groups,
            "n_agq": self.n_agq,
            "level": self.level,
            "converged": self.converged,
            "separation": self.separation,
            "separated_terms": list(self.separated_terms),
            "warnings": list(self.warnings),
            "iterations": self.iterations,
            "quadrature_shift": self.quadrature_shift,
        }


def _frozen(values: ArrayLike) -> FloatArray:
    out = np.array(values, dtype=np.float64)
    out.setflags(write=False)
    return out


# Plain logistic regression ------------------------------------------------------------


def _logistic_loglik(x: FloatArray, y: FloatArray, beta: FloatArray) -> float:
    eta = x @ beta
    return float(np.sum(y * eta - _softplus(eta)))


def _ascend(
    f: Callable[[FloatArray], float], point: FloatArray, value: float, step: FloatArray
) -> tuple[FloatArray, float] | None:
    """Try ``point + step``, halving the step until ``f`` does not decrease (None if never)."""
    scale = 1.0
    while scale > 1e-8:
        candidate = point + scale * step
        new = f(candidate)
        if new >= value:
            return candidate, new
        scale *= 0.5
    return None


def _logistic_newton(x: FloatArray, y: FloatArray, max_iter: int) -> tuple[FloatArray, float, int]:
    """Newton's method with step halving; stops when the step or the gain is tiny."""

    def loglik_at(beta: FloatArray) -> float:
        return _logistic_loglik(x, y, beta)

    beta = np.zeros(x.shape[1])
    loglik = loglik_at(beta)
    iterations = 0
    while iterations < max_iter:
        iterations += 1
        prob = _floats(expit(x @ beta))
        info = (x * (prob * (1.0 - prob))[:, None]).T @ x
        step = _solve_pd(info, x.T @ (y - prob))
        if step is None or float(np.max(np.abs(step))) < 1e-10:
            break
        found = _ascend(loglik_at, beta, loglik, step)
        if found is None:
            break
        gain = found[1] - loglik
        beta, loglik = found
        if gain < 1e-12 * (abs(loglik) + 0.1):
            break
    return beta, loglik, iterations


def _covariance(information: FloatArray, size: int) -> FloatArray | None:
    inverse = _inverse_pd(information)
    return None if inverse is None else inverse[:size, :size]


def fit_logistic(design: Design, level: float = 0.95, max_iter: int = 100) -> FitResult:
    """Maximum likelihood logistic regression of ``design.y`` on ``design.x``.

    Clusters in the design are ignored. See the module docstring for the
    convergence and separation rules.
    """
    level = _check_level(level)
    check = detect_separation(design)
    x, y = design.x, design.y
    beta, loglik, iterations = _logistic_newton(x, y, max_iter)
    prob = _floats(expit(x @ beta))
    info = (x * (prob * (1.0 - prob))[:, None]).T @ x
    step = _solve_pd(info, x.T @ (y - prob))
    cov = _covariance(info, design.n_params)
    warnings = _separation_warnings(check)
    if cov is None:
        warnings.append("information matrix is not positive definite; no standard errors")
        cov = np.full((design.n_params, design.n_params), np.nan)
    step_ok = step is not None and float(np.max(np.abs(step))) <= STEP_TOL
    converged = step_ok and not check.separated
    if not converged and not check.separated:
        warnings.append(f"Newton's method did not converge in {iterations} iterations")
    return FitResult(
        model="logistic",
        column_names=design.column_names,
        coef=_frozen(beta),
        cov=_frozen(cov),
        random_sd=None,
        log_likelihood=loglik,
        n_obs=design.n_obs,
        n_events=int(y.sum()),
        n_groups=None,
        n_agq=None,
        converged=converged,
        separation=check.separated,
        separated_terms=check.terms,
        warnings=tuple(warnings),
        iterations=iterations,
        level=level,
    )


# The random-intercept likelihood ------------------------------------------------------


class _MarginalLikelihood:
    """AGQ marginal log-likelihood of one dataset and its exact gradient.

    Observations are sorted by cluster so per-cluster sums are ``numpy.add.reduceat``
    calls. The modes from the last evaluation are kept as the next starting point.
    """

    def __init__(self, design: Design, n_agq: int) -> None:
        groups = _require_groups(design)
        order = np.argsort(groups, kind="stable")
        self.x: FloatArray = design.x[order]
        self.y: FloatArray = design.y[order]
        self.groups: IntArray = groups[order]
        self.starts: IntArray = np.flatnonzero(np.diff(self.groups, prepend=-1))
        nodes, weights = hermegauss(_check_n_agq(n_agq))
        self.nodes: FloatArray = np.asarray(nodes, dtype=np.float64)
        self.log_weights: FloatArray = np.log(np.asarray(weights, dtype=np.float64))
        self.modes: FloatArray = np.zeros(self.starts.size)

    def _sum(self, values: FloatArray) -> FloatArray:
        """Per-cluster sums over observations (axis 0)."""
        return np.asarray(np.add.reduceat(values, self.starts, axis=0), dtype=np.float64)

    def _find_modes(self, offset: FloatArray, sd: float) -> FloatArray:
        """Maximise ``sum_j log p(y_ij | offset_ij + sd u) - u^2 / 2`` over u, per cluster."""
        y, groups = self.y, self.groups
        u = self.modes.copy()
        eta = _floats(offset + sd * u[groups])
        value = self._sum(y * eta - _softplus(eta)) - 0.5 * u * u
        for _ in range(_MODE_MAX_ITER):
            prob = _floats(expit(eta))
            slope = sd * self._sum(y - prob) - u
            curvature = sd * sd * self._sum(prob * (1.0 - prob)) + 1.0
            step = slope / curvature
            scale = np.ones_like(u)
            for _ in range(_MAX_HALVINGS):
                trial = u + scale * step
                eta = _floats(offset + sd * trial[groups])
                trial_value = self._sum(y * eta - _softplus(eta)) - 0.5 * trial * trial
                worse = trial_value < value - 1e-12 * (1.0 + np.abs(value))
                if not worse.any():
                    break
                scale = np.where(worse, 0.5 * scale, scale)
            u, value = trial, trial_value
            if float(np.max(np.abs(scale * step))) < _MODE_TOL:
                break
        self.modes = u
        return u

    def evaluate(self, beta: FloatArray, sd: float) -> tuple[float, FloatArray]:
        """Log-likelihood and its gradient with respect to ``(beta, sd)``."""
        x, y, groups, t = self.x, self.y, self.groups, self.nodes
        offset = _floats(x @ beta)
        u = self._find_modes(offset, sd)
        # Quantities at the mode of each cluster.
        prob0 = _floats(expit(offset + sd * u[groups]))
        v0 = prob0 * (1.0 - prob0)
        v1 = v0 * (1.0 - 2.0 * prob0)
        sum_v0, sum_v1 = self._sum(v0), self._sum(v1)
        resid0 = self._sum(y - prob0)
        curv = sd * sd * sum_v0 + 1.0
        scale = _floats(1.0 / np.sqrt(curv))
        # Adaptive nodes and the quadrature sum, on the log scale.
        nodes = u[:, None] + scale[:, None] * t[None, :]
        eta = offset[:, None] + sd * nodes[groups]
        cond = self._sum(y[:, None] * eta - _softplus(eta))
        terms = self.log_weights + cond - 0.5 * nodes * nodes + 0.5 * t * t - 0.5 * _LOG_2PI
        total = np.asarray(logsumexp(terms, axis=1), dtype=np.float64)
        value = float(np.sum(np.log(scale) + total))
        # Gradient: implicit differentiation of the mode and of the curvature.
        weight = np.exp(terms - total[:, None])
        resid = y[:, None] - expit(eta)
        resid_sum = self._sum(resid)
        node_slope = weight * (sd * resid_sum - nodes)
        c_sum = node_slope.sum(axis=1)
        ct_sum = (node_slope * t).sum(axis=1)
        du_dbeta = (-sd / curv)[:, None] * self._sum(v0[:, None] * x)
        du_dsd = (resid0 - sd * u * sum_v0) / curv
        curv_u = sd**3 * sum_v1
        dcurv_dbeta = sd * sd * self._sum(v1[:, None] * x) + curv_u[:, None] * du_dbeta
        dcurv_dsd = 2.0 * sd * sum_v0 + sd * sd * sum_v1 * u + curv_u * du_dsd
        dlogscale_dbeta = (-0.5 / curv)[:, None] * dcurv_dbeta
        dlogscale_dsd = -0.5 * dcurv_dsd / curv
        node_factor = 1.0 + ct_sum * scale
        grad_beta = x.T @ np.sum(weight[groups] * resid, axis=1) + np.sum(
            node_factor[:, None] * dlogscale_dbeta + c_sum[:, None] * du_dbeta, axis=0
        )
        grad_sd = float(
            np.sum(weight * nodes * resid_sum)
            + np.sum(node_factor * dlogscale_dsd + c_sum * du_dsd)
        )
        return value, np.append(grad_beta, grad_sd)


def _parameters(design: Design, coef: Sequence[float] | FloatArray) -> FloatArray:
    beta = np.asarray(coef, dtype=np.float64)
    if beta.shape != (design.n_params,):
        raise ValueError(f"expected {design.n_params} coefficients, got shape {beta.shape}")
    return beta


def _sd_identified(model: _MarginalLikelihood) -> bool:
    """False when every cluster's outcomes are all equal (the SD estimate is infinite)."""
    low = np.minimum.reduceat(model.y, model.starts)
    high = np.maximum.reduceat(model.y, model.starts)
    return bool(np.any(low != high))


def marginal_log_likelihood(
    design: Design, coef: Sequence[float] | FloatArray, sd: float, n_agq: int = 1
) -> float:
    """AGQ marginal log-likelihood of the random-intercept model at ``(coef, sd)``."""
    beta = _parameters(design, coef)
    return _MarginalLikelihood(design, n_agq).evaluate(beta, float(sd))[0]


def marginal_score(
    design: Design, coef: Sequence[float] | FloatArray, sd: float, n_agq: int = 1
) -> FloatArray:
    """Gradient of :func:`marginal_log_likelihood` with respect to ``(coef..., sd)``."""
    beta = _parameters(design, coef)
    return _MarginalLikelihood(design, n_agq).evaluate(beta, float(sd))[1]


# Fitting the mixed model --------------------------------------------------------------


def _fd_hessian(objective: Objective, theta: FloatArray) -> FloatArray:
    """Symmetrised central-difference Hessian of an objective with an exact gradient."""
    k = theta.size
    hessian = np.empty((k, k))
    for j in range(k):
        h = _FD_STEP * max(1.0, abs(float(theta[j])))
        up, down = theta.copy(), theta.copy()
        up[j] += h
        down[j] -= h
        hessian[:, j] = (objective(up)[1] - objective(down)[1]) / (2.0 * h)
    return 0.5 * (hessian + hessian.T)


def _refine(
    objective: Objective, theta: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, int]:
    """Newton steps from ``theta``; returns the point, its gradient, Hessian, and step count."""
    value, grad = objective(theta)
    hessian = _fd_hessian(objective, theta)
    steps = 0
    for _ in range(_NEWTON_REFINEMENTS):
        step = _solve_pd(hessian, grad)
        if step is None or float(np.max(np.abs(step))) < 1e-12:
            break
        candidate = theta - step
        new_value, new_grad = objective(candidate)
        if not new_value < value:
            break
        theta, value, grad = candidate, new_value, new_grad
        hessian = _fd_hessian(objective, theta)
        steps += 1
    return theta, grad, hessian, steps


def fit_glmm(
    design: Design, n_agq: int = 1, level: float = 0.95, max_iter: int = 1000
) -> FitResult:
    """Fit the random-intercept logistic model by maximum likelihood (module docstring).

    Args:
        design: Design with clusters (at least two).
        n_agq: Quadrature nodes per cluster; 1 is the Laplace approximation.
        level: Coverage level of the Wald intervals.
        max_iter: Iteration cap for BFGS.

    Raises:
        ValueError: The design has fewer than two clusters, or ``n_agq`` or ``level``
            is out of range. Separation and non-convergence are reported, not raised.
    """
    level = _check_level(level)
    n_agq = _check_n_agq(n_agq)
    model = _MarginalLikelihood(design, n_agq)
    check = detect_separation(design)
    p = design.n_params
    start, _, _ = _logistic_newton(design.x, design.y, 100)

    def objective(theta: FloatArray) -> tuple[float, FloatArray]:
        value, grad = model.evaluate(theta[:p], float(theta[p]))
        return -value, -grad

    result = minimize(
        objective,
        np.append(start, 1.0),
        jac=True,
        method="BFGS",
        options={"gtol": 1e-6, "maxiter": max_iter},
    )
    theta = np.array(result.x, dtype=np.float64)
    theta[p] = abs(theta[p])
    theta, grad, hessian, refinements = _refine(objective, theta)
    if theta[p] < 0:
        # The likelihood is even in sd: reflect the point, gradient, and Hessian to sd > 0.
        theta, grad, hessian = theta.copy(), grad.copy(), hessian.copy()
        theta[p], grad[p] = -theta[p], -grad[p]
        hessian[p, :p] *= -1.0
        hessian[:p, p] *= -1.0
    sd = float(theta[p])
    warnings = _separation_warnings(check)
    full_step = _solve_pd(hessian, grad)
    cov = _covariance(hessian, p)
    if full_step is not None:
        step_ok = float(np.max(np.abs(full_step))) <= STEP_TOL
    else:
        near_zero = sd < 1e-3
        block_step = _solve_pd(hessian[:p, :p], grad[:p])
        cov = _inverse_pd(hessian[:p, :p])
        step_ok = (
            near_zero and block_step is not None and float(np.max(np.abs(block_step))) <= STEP_TOL
        )
        if cov is not None:
            where = "the SD is at or next to 0" if near_zero else "the SD is poorly determined"
            warnings.append(
                f"the Hessian over all parameters is not positive definite ({where}); "
                "fixed-effect SEs treat the random-intercept SD as known"
            )
    if cov is None:
        warnings.append("the Hessian is not positive definite; no standard errors")
        cov = np.full((p, p), np.nan)
    identified = _sd_identified(model)
    if not identified:
        warnings.append(
            "every cluster has all-equal outcomes, so the random-intercept SD is not "
            "identified (its maximum likelihood estimate is infinite)"
        )
    if sd >= SD_LIMIT:
        warnings.append(
            f"random-intercept SD reached {sd:.3g} (limit {SD_LIMIT:g} on the logit scale): "
            "clusters with all-equal outcomes push it towards infinity"
        )
    finite = bool(np.all(np.isfinite(theta)))
    converged = step_ok and identified and sd < SD_LIMIT and finite and not check.separated
    if not converged and identified and not check.separated and sd < SD_LIMIT:
        warnings.append(f"the optimiser did not reach a converged maximum ({result.message})")
    shift = None
    if n_agq < CHECK_AGQ and full_step is not None and not check.separated:
        _, reference_grad = _MarginalLikelihood(design, CHECK_AGQ).evaluate(theta[:p], sd)
        # ``-grad`` is the n_agq score, so this is H^-1 (score_check - score_n_agq): the
        # difference of the two Newton steps, without the step left by an early stop.
        predicted = _solve_pd(hessian, reference_grad + grad)
        shift = None if predicted is None else float(np.max(np.abs(predicted)))
        if shift is not None and shift > QUADRATURE_TOL:
            warnings.append(
                f"quadrature: with {CHECK_AGQ} nodes the estimates would change by up to "
                f"{shift:.3g}; refit with a larger n_agq"
            )
    return FitResult(
        model="glmm",
        column_names=design.column_names,
        coef=_frozen(theta[:p]),
        cov=_frozen(cov),
        random_sd=sd,
        log_likelihood=-objective(theta)[0],
        n_obs=design.n_obs,
        n_events=int(design.y.sum()),
        n_groups=design.n_groups,
        n_agq=n_agq,
        converged=converged,
        separation=check.separated,
        separated_terms=check.terms,
        warnings=tuple(warnings),
        iterations=int(result.nit) + refinements,
        level=level,
        quadrature_shift=shift,
    )


# Likelihood-ratio tests -----------------------------------------------------------------


@dataclass(frozen=True)
class LikelihoodRatioTest:
    """A likelihood-ratio test of a restricted model against a fuller one.

    Attributes:
        statistic: ``2 (log L_full - log L_restricted)``, floored at 0.
        df: Difference in the number of parameters.
        p_value: Upper-tail probability under the reference distribution.
        boundary: True when the reference distribution is the 50:50 mixture of
            chi-square with ``df - 1`` and ``df`` degrees of freedom, used when the
            full model adds the random-intercept SD (tested on its boundary, 0).
    """

    statistic: float
    df: int
    p_value: float
    boundary: bool


def likelihood_ratio_test(
    restricted: FitResult, full: FitResult, boundary: bool | None = None
) -> LikelihoodRatioTest:
    """Likelihood-ratio test for nested models fitted to the same data.

    Nesting is checked as far as the fits allow: the same number of observations
    and events, every restricted column present in the full model, more parameters
    in the full model, and no random intercept in the restricted model unless the
    full model has one too. Two GLMMs must use the same ``n_agq``, because their
    log-likelihoods are approximations of different accuracy otherwise.
    ``boundary`` defaults to True exactly when the full model is a GLMM and the
    restricted model is a plain logistic regression.

    Raises:
        ValueError: The fits are not nested, not fitted to the same data, or GLMMs
            fitted with different ``n_agq``.
    """
    if (restricted.n_obs, restricted.n_events) != (full.n_obs, full.n_events):
        raise ValueError("the two fits are not of the same data")
    if not set(restricted.column_names) <= set(full.column_names):
        raise ValueError("models are not nested: the restricted model has other columns")
    if restricted.model == "glmm" and full.model == "logistic":
        raise ValueError("models are not nested: only the restricted model has a random intercept")
    if restricted.model == full.model == "glmm" and restricted.n_agq != full.n_agq:
        raise ValueError(
            f"the GLMMs were fitted with different n_agq ({restricted.n_agq} and {full.n_agq})"
        )
    df = full.n_params - restricted.n_params
    if df < 1:
        raise ValueError("the full model must have more parameters than the restricted one")
    if boundary is None:
        boundary = restricted.model == "logistic" and full.model == "glmm"
    statistic = max(0.0, 2.0 * (full.log_likelihood - restricted.log_likelihood))
    upper = float(chi2.sf(statistic, df))
    if boundary:
        lower = float(chi2.sf(statistic, df - 1)) if df > 1 else float(statistic <= 0.0)
        p_value = 0.5 * lower + 0.5 * upper
    else:
        p_value = upper
    return LikelihoodRatioTest(statistic=statistic, df=df, p_value=p_value, boundary=boundary)


# Cluster bootstrap of the coefficients --------------------------------------------------


def bootstrap_coefficients(
    records: Sequence[Mapping[str, Any]],
    formula: Formula,
    *,
    model: Literal["glmm", "logistic"] = "glmm",
    n_agq: int = 1,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> dict[str, BootstrapResult]:
    """Cluster bootstrap percentile intervals for every fixed effect of a model.

    The clusters are the values of ``formula.group`` (the tasks). Each replicate
    resamples them with replacement by the scheme of
    :func:`receipts.analysis.rates.cluster_bootstrap`, gives each drawn copy of a
    cluster its own label (:func:`receipts.analysis.rates.relabel_field`) so a task
    drawn twice counts as two tasks with their own random intercepts, rebuilds the
    design with the reference levels of the original data, and refits ``model``
    (:func:`fit_glmm` with ``n_agq`` nodes, or :func:`fit_logistic`).

    A replicate whose design cannot be built (for example no drawn task has a
    reference level) or whose fit did not converge or is separated gives NaN for
    every term; a replicate that lacks one non-reference level gives NaN for that
    level's column only. NaN replicates are dropped and counted in ``n_nonfinite``.
    Dropping them is not neutral: separated replicates have the most extreme
    estimates, so an interval that dropped many replicates is too narrow, and the
    count belongs next to it in any report. When the fit to the original records
    fails in the same way, every ``estimate`` is NaN. Odds-ratio intervals are
    ``exp`` of the bounds (percentile intervals respect monotone transformations).

    Args:
        records: The observations, one mapping per run.
        formula: The model formula; ``formula.group`` names the cluster field.
        model: ``"glmm"`` (random intercept per cluster) or ``"logistic"``.
        n_agq: Quadrature nodes per cluster for ``"glmm"`` fits.
        n_boot: Number of replicates.
        seed: Seed for ``numpy.random.default_rng``.
        level: Interval coverage level in ``(0, 1)``.

    Returns:
        One result per column of the design of ``records``, in column order, on the
        log-odds scale.

    Raises:
        ValueError: ``formula.group`` is None, ``model`` or ``n_agq`` is invalid, no
            design can be built from ``records``, or the options are out of range.
    """
    group = formula.group
    if group is None:
        raise ValueError("a cluster bootstrap needs formula.group (the cluster field)")
    if model not in ("glmm", "logistic"):
        raise ValueError(f"model must be 'glmm' or 'logistic', got {model!r}")
    n_agq = _check_n_agq(n_agq)
    original = build_design(records, formula)
    fixed = replace(formula, reference={f: original.levels[f][0] for f in formula.factors})

    def coefficients(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
        try:
            design = build_design(rows, fixed)
        except ValueError:
            return {}
        fit = fit_glmm(design, n_agq=n_agq) if model == "glmm" else fit_logistic(design)
        if not fit.converged or fit.separation:
            return {}
        return {name: float(value) for name, value in zip(fit.column_names, fit.coef, strict=True)}

    return cluster_bootstrap_many(
        records,
        coefficients,
        group,
        n_boot,
        seed,
        level,
        names=original.column_names,
        relabel=relabel_field(group),
    )
