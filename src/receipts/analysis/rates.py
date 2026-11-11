"""Binomial rates with Wilson score intervals, and cluster bootstrap intervals.

Rates (false-success rate, contradicted-claim rate, failure-omission rate) are
reported with two kinds of interval:

- :func:`rate_with_ci`: the Wilson score interval, which treats every trial as
  independent. It is the interval ``tools/ship_check.py`` recomputes.
- :func:`cluster_bootstrap`: a percentile bootstrap that resamples whole clusters
  (tasks) with replacement, so outcomes that are correlated within a task do not
  make the interval too narrow. :func:`cluster_bootstrap_many` does the same for
  several statistics computed together (for example every coefficient of one model
  fit), and :func:`paired_cluster_bootstrap` for the difference between two
  conditions run on the same tasks.

Resampling scheme (so a reader can reproduce any interval exactly): clusters are
numbered in order of first appearance in ``records``; the generator is
``numpy.random.default_rng(seed)``; one call
``rng.integers(0, n_clusters, size=(n_boot, n_clusters))`` draws every replicate;
replicate ``b`` concatenates the records of the clusters in row ``b`` (a cluster
drawn twice appears twice) and evaluates the statistic on them. With ``relabel``,
every record of the cluster drawn at position ``k`` (0-based) of the row is passed
through ``relabel(record, k)`` first, so a statistic that groups records by cluster
(such as a model with a random intercept per task) sees each copy of a cluster drawn
twice as its own cluster; :func:`relabel_field` builds such a function. Replicates
where the statistic is NaN or infinite are dropped and counted in ``n_nonfinite``.
The interval is ``numpy.quantile`` (linear interpolation) of the remaining
replicates at ``(1 - level) / 2`` and ``(1 + level) / 2``.

Percentile intervals are approximate: with few clusters (tens of tasks) they tend
to cover slightly less often than ``level``. ``tests/analysis/test_rates.py``
measures coverage on synthetic clustered data with 30 clusters.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from itertools import chain
from typing import Any, SupportsIndex, TypeVar, cast

import numpy as np
from numpy.typing import NDArray

R = TypeVar("R")

Z95: float = 1.959963984540054
"""Standard normal 0.975 quantile, for two-sided 95 percent intervals."""

BOOTSTRAP_METHOD = "cluster percentile bootstrap"


def wilson_interval(
    successes: SupportsIndex, n: SupportsIndex, z: float = Z95
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Args:
        successes: Number of successes, an integer in ``[0, n]``.
        n: Number of trials, a non-negative integer.
        z: Standard normal quantile; the default gives a two-sided 95% interval.

    Returns:
        ``(low, high)``, clipped to ``[0, 1]``. With ``n == 0`` the interval is the
        vacuous ``(0.0, 1.0)``, the same convention as ``tools/ship_check.py``.

    Raises:
        TypeError: ``successes`` or ``n`` is not an integer.
        ValueError: The counts are out of range or ``z`` is not positive and finite.
    """
    k, m = operator.index(successes), operator.index(n)
    if m < 0 or not 0 <= k <= m:
        raise ValueError(f"need 0 <= successes <= n, got successes={k}, n={m}")
    if not (math.isfinite(z) and z > 0):
        raise ValueError(f"z must be positive and finite, got {z}")
    if m == 0:
        return (0.0, 1.0)
    p = k / m
    denom = 1 + z * z / m
    centre = (p + z * z / (2 * m)) / denom
    half = z * math.sqrt(p * (1 - p) / m + z * z / (4 * m * m)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class RateCI:
    """A binomial rate with its Wilson score interval.

    Attributes:
        successes: Count of successes.
        n: Count of trials.
        estimate: ``successes / n``, or NaN when ``n == 0``.
        ci_low: Lower bound of the Wilson interval.
        ci_high: Upper bound of the Wilson interval.
        z: Normal quantile used for the interval.
    """

    successes: int
    n: int
    estimate: float
    ci_low: float
    ci_high: float
    z: float

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready mapping with ``estimate``, ``ci_low``, ``ci_high``, and the counts."""
        return {**asdict(self), "method": "wilson"}


def rate_with_ci(successes: SupportsIndex, n: SupportsIndex, z: float = Z95) -> RateCI:
    """Rate ``successes / n`` with its Wilson score interval (see :func:`wilson_interval`)."""
    k, m = operator.index(successes), operator.index(n)
    low, high = wilson_interval(k, m, z)
    estimate = k / m if m else math.nan
    return RateCI(successes=k, n=m, estimate=estimate, ci_low=low, ci_high=high, z=z)


def mean_statistic(field: str) -> Callable[[Sequence[Mapping[str, Any]]], float]:
    """Statistic: the mean of ``record[field]`` (booleans count as 0 or 1); NaN when empty."""

    def mean(records: Sequence[Mapping[str, Any]]) -> float:
        if not records:
            return math.nan
        return sum(float(r[field]) for r in records) / len(records)

    return mean


def ratio_statistic(
    numerator: str, denominator: str
) -> Callable[[Sequence[Mapping[str, Any]]], float]:
    """Statistic: ``sum(numerator) / sum(denominator)`` over records; NaN when the sum is 0.

    For example the contradicted-claim rate pooled over runs, with one record per run
    holding the run's contradicted count and claim count.
    """

    def ratio(records: Sequence[Mapping[str, Any]]) -> float:
        den = sum(float(r[denominator]) for r in records)
        if den == 0:
            return math.nan
        return sum(float(r[numerator]) for r in records) / den

    return ratio


@dataclass(frozen=True)
class BootstrapResult:
    """A cluster bootstrap estimate with its percentile interval.

    Attributes:
        estimate: The statistic on the original records.
        ci_low: Lower percentile bound (NaN if no replicate was finite).
        ci_high: Upper percentile bound (NaN if no replicate was finite).
        n_boot: Number of bootstrap replicates drawn.
        n_clusters: Number of clusters resampled.
        level: Interval coverage level, for example 0.95.
        n_nonfinite: Replicates dropped because the statistic was NaN or infinite.
        seed: Seed passed to ``numpy.random.default_rng``.
    """

    estimate: float
    ci_low: float
    ci_high: float
    n_boot: int
    n_clusters: int
    level: float
    n_nonfinite: int
    seed: int

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready mapping of every field plus the method name."""
        return {**asdict(self), "method": BOOTSTRAP_METHOD}


@dataclass(frozen=True)
class PairedBootstrapResult(BootstrapResult):
    """A paired cluster bootstrap of ``statistic(treatment) - statistic(control)``.

    ``estimate`` (``treatment_estimate - control_estimate``), ``ci_low``, and
    ``ci_high`` refer to the difference. Only clusters that contain both conditions
    are used; ``n_clusters`` counts them.

    Attributes:
        treatment_estimate: The statistic on the treatment records of paired clusters.
        control_estimate: The statistic on the control records of paired clusters.
        n_unpaired_clusters: Clusters dropped because they lack one of the conditions.
    """

    treatment_estimate: float
    control_estimate: float
    n_unpaired_clusters: int


def _key_function(key: str | Callable[[R], Hashable]) -> Callable[[R], Hashable]:
    if isinstance(key, str):
        name = key

        def by_name(record: R) -> Hashable:
            return cast(Hashable, cast(Mapping[str, Any], record)[name])

        return by_name
    return key


def _group(records: Sequence[R], key: Callable[[R], Hashable]) -> dict[Hashable, list[R]]:
    groups: dict[Hashable, list[R]] = {}
    for record in records:
        groups.setdefault(key(record), []).append(record)
    return groups


def _check_options(n_boot: int, level: float) -> None:
    if operator.index(n_boot) < 1:
        raise ValueError(f"n_boot must be at least 1, got {n_boot}")
    if not 0 < level < 1:
        raise ValueError(f"level must be in (0, 1), got {level}")


def _percentile_interval(reps: NDArray[np.float64], level: float) -> tuple[float, float, int]:
    finite = reps[np.isfinite(reps)]
    n_nonfinite = int(reps.size - finite.size)
    if finite.size == 0:
        return math.nan, math.nan, n_nonfinite
    alpha = 1.0 - level
    low, high = np.quantile(finite, [alpha / 2, 1 - alpha / 2])
    return float(low), float(high), n_nonfinite


def relabel_field(field: str) -> Callable[[Mapping[str, Any], int], dict[str, Any]]:
    """A ``relabel`` function for mapping records: ``record[field]`` becomes ``"k:value"``.

    ``k`` is the position (0-based) at which the record's cluster was drawn in a
    replicate, so the copies of a cluster drawn twice get different labels. Labels
    from different positions never coincide, because the position ends at the first
    colon. The record is copied, never modified.
    """

    def relabel(record: Mapping[str, Any], position: int) -> dict[str, Any]:
        return {**record, field: f"{position}:{record[field]}"}

    return relabel


def _assemble(
    clusters: Sequence[Sequence[R]], row: Sequence[int], relabel: Callable[[R, int], R] | None
) -> list[R]:
    """The records of the clusters in ``row``, in draw order (module docstring)."""
    if relabel is None:
        return list(chain.from_iterable([clusters[i] for i in row]))
    return [relabel(record, position) for position, i in enumerate(row) for record in clusters[i]]


def _draws(n_clusters: int, n_boot: int, seed: int) -> list[list[int]]:
    """Cluster indices of every replicate, one row per replicate (module docstring)."""
    rng = np.random.default_rng(seed)
    rows: list[list[int]] = rng.integers(0, n_clusters, size=(n_boot, n_clusters)).tolist()
    return rows


def _replicates(
    clusters: Sequence[Sequence[R]],
    n_boot: int,
    seed: int,
    relabel: Callable[[R, int], R] | None,
) -> Iterator[list[R]]:
    for row in _draws(len(clusters), n_boot, seed):
        yield _assemble(clusters, row, relabel)


def _clusters(records: Sequence[R], cluster_key: str | Callable[[R], Hashable]) -> list[list[R]]:
    if not records:
        raise ValueError("a cluster bootstrap needs at least one record")
    return list(_group(records, _key_function(cluster_key)).values())


def cluster_bootstrap(
    records: Sequence[R],
    statistic: Callable[[Sequence[R]], float],
    cluster_key: str | Callable[[R], Hashable],
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
    *,
    relabel: Callable[[R, int], R] | None = None,
) -> BootstrapResult:
    """Percentile interval for ``statistic`` from resampling clusters with replacement.

    Args:
        records: The observations, for example one mapping per run.
        statistic: Function of a list of records returning a number.
        cluster_key: Field name holding the cluster (task) ID, or a function of a record.
        n_boot: Number of replicates.
        seed: Seed for ``numpy.random.default_rng``.
        level: Interval coverage level in ``(0, 1)``.
        relabel: Optional ``(record, position) -> record`` applied to resampled
            records so repeated draws of a cluster count as different clusters (for
            example ``relabel_field("task_id")``); the estimate uses the records as given.

    Returns:
        The estimate on all records and the percentile interval; the resampling
        scheme is described in the module docstring.

    Raises:
        ValueError: ``records`` is empty, ``n_boot < 1``, or ``level`` is outside ``(0, 1)``.
    """
    _check_options(n_boot, level)
    clusters = _clusters(records, cluster_key)
    reps = np.array(
        [float(statistic(rows)) for rows in _replicates(clusters, n_boot, seed, relabel)],
        dtype=np.float64,
    )
    low, high, n_nonfinite = _percentile_interval(reps, level)
    return BootstrapResult(
        estimate=float(statistic(records)),
        ci_low=low,
        ci_high=high,
        n_boot=int(n_boot),
        n_clusters=len(clusters),
        level=level,
        n_nonfinite=n_nonfinite,
        seed=seed,
    )


def cluster_bootstrap_many(
    records: Sequence[R],
    statistic: Callable[[Sequence[R]], Mapping[str, float]],
    cluster_key: str | Callable[[R], Hashable],
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
    *,
    names: Sequence[str] | None = None,
    relabel: Callable[[R, int], R] | None = None,
) -> dict[str, BootstrapResult]:
    """Cluster bootstrap of several statistics computed together on each replicate.

    ``statistic`` returns a mapping from name to value, for example every coefficient
    of one model fit, so each replicate is computed once. Every name uses the same
    resampled clusters: with the same seed, each result equals what
    :func:`cluster_bootstrap` gives for that name alone. A name missing from the
    mapping of a replicate counts as a non-finite replicate for that name, and one
    missing from the mapping on the original records has a NaN estimate.

    Args:
        records: The observations.
        statistic: Function of a list of records returning a mapping of numbers.
        cluster_key: Field name holding the cluster (task) ID, or a function of a record.
        n_boot: Number of replicates.
        seed: Seed for ``numpy.random.default_rng``.
        level: Interval coverage level in ``(0, 1)``.
        names: The names to report, in order; default the keys of
            ``statistic(records)``.
        relabel: As for :func:`cluster_bootstrap`.

    Returns:
        One :class:`BootstrapResult` per name, in order.

    Raises:
        ValueError: ``records`` is empty, there are no names, a name repeats, or the
            options are out of range.
    """
    _check_options(n_boot, level)
    clusters = _clusters(records, cluster_key)
    observed = statistic(records)
    keys = [str(k) for k in (observed if names is None else names)]
    if not keys:
        raise ValueError("no statistics to bootstrap: the statistic returned no names")
    if len(set(keys)) != len(keys):
        raise ValueError("statistic names must be unique")
    reps = np.full((n_boot, len(keys)), math.nan)
    for b, rows in enumerate(_replicates(clusters, n_boot, seed, relabel)):
        values = statistic(rows)
        reps[b] = [float(values.get(key, math.nan)) for key in keys]
    results: dict[str, BootstrapResult] = {}
    for j, key in enumerate(keys):
        low, high, n_nonfinite = _percentile_interval(reps[:, j], level)
        results[key] = BootstrapResult(
            estimate=float(observed.get(key, math.nan)),
            ci_low=low,
            ci_high=high,
            n_boot=int(n_boot),
            n_clusters=len(clusters),
            level=level,
            n_nonfinite=n_nonfinite,
            seed=seed,
        )
    return results


def paired_cluster_bootstrap(
    records: Sequence[R],
    statistic: Callable[[Sequence[R]], float],
    cluster_key: str | Callable[[R], Hashable],
    condition_key: str | Callable[[R], Hashable],
    treatment: Hashable,
    control: Hashable,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
    *,
    relabel: Callable[[R, int], R] | None = None,
) -> PairedBootstrapResult:
    """Paired cluster bootstrap for a difference between two conditions within tasks.

    Each replicate resamples clusters that ran both conditions, keeping a cluster's
    treatment and control records together, and evaluates
    ``statistic(treatment records) - statistic(control records)``. Records whose
    condition is neither ``treatment`` nor ``control`` are ignored. The resampling
    scheme is the one in the module docstring, over the paired clusters; ``relabel``
    gives both arms of a cluster drawn at position ``k`` the same new label.

    Args:
        records: The observations.
        statistic: Function of a list of records returning a number.
        cluster_key: Field name or function giving the cluster (task) ID.
        condition_key: Field name or function giving the condition of a record.
        treatment: Condition value of the treatment arm.
        control: Condition value of the control arm.
        n_boot: Number of replicates.
        seed: Seed for ``numpy.random.default_rng``.
        level: Interval coverage level in ``(0, 1)``.
        relabel: As for :func:`cluster_bootstrap`.

    Raises:
        ValueError: The two conditions are equal, no cluster contains both, or the
            options are out of range.
    """
    _check_options(n_boot, level)
    if treatment == control:
        raise ValueError("treatment and control conditions must differ")
    condition = _key_function(condition_key)
    treated_clusters: list[list[R]] = []
    control_clusters: list[list[R]] = []
    unpaired = 0
    for members in _group(records, _key_function(cluster_key)).values():
        treated = [r for r in members if condition(r) == treatment]
        controls = [r for r in members if condition(r) == control]
        if treated and controls:
            treated_clusters.append(treated)
            control_clusters.append(controls)
        elif treated or controls:
            unpaired += 1
    if not treated_clusters:
        raise ValueError("no cluster contains both the treatment and the control condition")
    treatment_estimate = float(statistic(list(chain.from_iterable(treated_clusters))))
    control_estimate = float(statistic(list(chain.from_iterable(control_clusters))))
    reps = np.array(
        [
            float(statistic(_assemble(treated_clusters, row, relabel)))
            - float(statistic(_assemble(control_clusters, row, relabel)))
            for row in _draws(len(treated_clusters), n_boot, seed)
        ],
        dtype=np.float64,
    )
    low, high, n_nonfinite = _percentile_interval(reps, level)
    return PairedBootstrapResult(
        estimate=treatment_estimate - control_estimate,
        ci_low=low,
        ci_high=high,
        n_boot=int(n_boot),
        n_clusters=len(treated_clusters),
        level=level,
        n_nonfinite=n_nonfinite,
        seed=seed,
        treatment_estimate=treatment_estimate,
        control_estimate=control_estimate,
        n_unpaired_clusters=unpaired,
    )
