"""Tests for receipts.analysis.rates.

Every dataset here is synthetic: generated in the test from a fixed seed or written
by hand for one property, never taken from an agent run.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pytest
from scipy.stats import binomtest

from receipts.analysis.rates import (
    Z95,
    BootstrapResult,
    PairedBootstrapResult,
    RateCI,
    cluster_bootstrap,
    cluster_bootstrap_many,
    mean_statistic,
    paired_cluster_bootstrap,
    rate_with_ci,
    ratio_statistic,
    relabel_field,
    wilson_interval,
)

Record = Mapping[str, Any]


def synthetic_clustered(
    rng: np.random.Generator, n_clusters: int, per_cluster: int, a: float, b: float
) -> list[dict[str, Any]]:
    """Synthetic clustered binary records: cluster rates drawn from Beta(a, b)."""
    records: list[dict[str, Any]] = []
    for c in range(n_clusters):
        p = rng.beta(a, b)
        for _ in range(per_cluster):
            records.append({"task": f"t{c}", "y": int(rng.random() < p), "synthetic": True})
    return records


# Wilson score interval ----------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "n"), [(0, 1), (1, 1), (0, 10), (3, 10), (10, 10), (81, 263), (15, 148), (1, 29)]
)
def test_wilson_matches_scipy(k: int, n: int) -> None:
    ci = binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson")
    lo, hi = wilson_interval(k, n)
    assert lo == pytest.approx(float(ci.low), abs=1e-12)
    assert hi == pytest.approx(float(ci.high), abs=1e-12)


def test_wilson_closed_forms_at_the_edges() -> None:
    # Hand-computed: with 0 successes the upper bound is z^2 / (n + z^2); with n
    # successes the lower bound is n / (n + z^2).
    z2 = Z95 * Z95
    assert wilson_interval(0, 10) == pytest.approx((0.0, z2 / (10 + z2)), abs=1e-12)
    assert wilson_interval(0, 10)[1] == pytest.approx(0.27754, abs=1e-5)
    assert wilson_interval(20, 20) == pytest.approx((20 / (20 + z2), 1.0), abs=1e-12)


def test_wilson_other_levels_and_empty() -> None:
    lo90, hi90 = wilson_interval(30, 100, z=1.6448536269514722)
    ci = binomtest(30, 100).proportion_ci(confidence_level=0.90, method="wilson")
    assert (lo90, hi90) == pytest.approx((float(ci.low), float(ci.high)), abs=1e-12)
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_accepts_numpy_integers() -> None:
    assert wilson_interval(np.int64(3), np.int64(10)) == wilson_interval(3, 10)


@pytest.mark.parametrize(
    ("k", "n", "z"), [(-1, 5, Z95), (6, 5, Z95), (0, -1, Z95), (1, 5, 0.0), (1, 5, math.nan)]
)
def test_wilson_rejects_bad_input(k: int, n: int, z: float) -> None:
    with pytest.raises(ValueError):
        wilson_interval(k, n, z)


def test_wilson_rejects_non_integers() -> None:
    with pytest.raises(TypeError):
        wilson_interval(1.5, 4)  # type: ignore[arg-type]  # deliberate wrong type


def test_rate_with_ci() -> None:
    rate = rate_with_ci(3, 12)
    assert isinstance(rate, RateCI)
    assert rate.estimate == 0.25
    assert (rate.ci_low, rate.ci_high) == wilson_interval(3, 12)
    assert rate.ci_low <= rate.estimate <= rate.ci_high
    assert rate.as_dict() == {
        "estimate": 0.25,
        "ci_low": rate.ci_low,
        "ci_high": rate.ci_high,
        "successes": 3,
        "n": 12,
        "z": Z95,
        "method": "wilson",
    }


def test_rate_with_ci_empty_has_nan_estimate() -> None:
    rate = rate_with_ci(0, 0)
    assert math.isnan(rate.estimate)
    assert (rate.ci_low, rate.ci_high) == (0.0, 1.0)


# Statistic helpers ----------------------------------------------------------------


def test_mean_and_ratio_statistics() -> None:
    rows = [{"y": 1, "c": 2, "k": 3}, {"y": 0, "c": 1, "k": 1}, {"y": True, "c": 0, "k": 0}]
    assert mean_statistic("y")(rows) == pytest.approx(2 / 3)
    assert ratio_statistic("c", "k")(rows) == pytest.approx(3 / 4)
    assert math.isnan(mean_statistic("y")([]))
    assert math.isnan(ratio_statistic("c", "k")([{"c": 0, "k": 0}]))


# Cluster bootstrap ----------------------------------------------------------------


def test_cluster_bootstrap_is_seeded_and_reproducible() -> None:
    records = synthetic_clustered(np.random.default_rng(1), 12, 5, 2.0, 5.0)
    stat = mean_statistic("y")
    first = cluster_bootstrap(records, stat, "task", n_boot=300, seed=7)
    again = cluster_bootstrap(records, stat, "task", n_boot=300, seed=7)
    other = cluster_bootstrap(records, stat, "task", n_boot=300, seed=8)
    assert first == again
    assert first != other
    assert isinstance(first, BootstrapResult)
    assert first.estimate == pytest.approx(stat(records))
    assert first.ci_low <= first.estimate <= first.ci_high
    assert (first.n_boot, first.n_clusters, first.n_nonfinite, first.seed) == (300, 12, 0, 7)


def test_cluster_bootstrap_matches_documented_algorithm() -> None:
    """Reimplement the documented resampling scheme and compare exactly."""
    records = synthetic_clustered(np.random.default_rng(2), 6, 4, 1.0, 1.0)
    stat = mean_statistic("y")
    result = cluster_bootstrap(records, stat, "task", n_boot=200, seed=11, level=0.9)
    clusters: dict[str, list[Record]] = {}
    for r in records:
        clusters.setdefault(str(r["task"]), []).append(r)
    groups = list(clusters.values())
    rng = np.random.default_rng(11)
    draws = rng.integers(0, len(groups), size=(200, len(groups)))
    reps = np.array([stat([r for i in row for r in groups[i]]) for row in draws])
    lo, hi = np.quantile(reps, [0.05, 0.95])
    assert (result.ci_low, result.ci_high) == (float(lo), float(hi))


def test_cluster_bootstrap_key_function_equals_field_name() -> None:
    records = synthetic_clustered(np.random.default_rng(3), 8, 3, 2.0, 2.0)
    stat = mean_statistic("y")
    by_name = cluster_bootstrap(records, stat, "task", n_boot=100, seed=0)
    by_func = cluster_bootstrap(records, stat, lambda r: r["task"], n_boot=100, seed=0)
    assert by_name == by_func


def test_cluster_bootstrap_resamples_whole_clusters() -> None:
    # Two clusters whose records are identical within each cluster, but the
    # clusters differ: every replicate mean is 0, 1/2, or 1, never anything else.
    records = [{"task": "a", "y": 0}] * 3 + [{"task": "b", "y": 1}] * 3
    result = cluster_bootstrap(records, mean_statistic("y"), "task", n_boot=500, seed=0)
    assert result.estimate == 0.5
    assert (result.ci_low, result.ci_high) == (0.0, 1.0)


def test_cluster_bootstrap_single_cluster_is_degenerate() -> None:
    records = [{"task": "a", "y": v} for v in (0, 1, 1, 0, 1)]
    result = cluster_bootstrap(records, mean_statistic("y"), "task", n_boot=50, seed=0)
    assert (result.ci_low, result.estimate, result.ci_high) == (0.6, 0.6, 0.6)
    assert result.n_clusters == 1


def test_cluster_bootstrap_drops_nonfinite_replicates() -> None:
    # Cluster "z" has no claims, so replicates made only of "z" have a 0/0 ratio.
    records = [{"task": "a", "c": 1, "k": 2}, {"task": "z", "c": 0, "k": 0}]
    result = cluster_bootstrap(records, ratio_statistic("c", "k"), "task", n_boot=400, seed=4)
    assert 0 < result.n_nonfinite < 400
    assert result.ci_low == result.ci_high == 0.5


def test_cluster_bootstrap_all_nonfinite_gives_nan_interval() -> None:
    records = [{"task": "a", "c": 0, "k": 0}, {"task": "b", "c": 0, "k": 0}]
    result = cluster_bootstrap(records, ratio_statistic("c", "k"), "task", n_boot=20, seed=0)
    assert result.n_nonfinite == 20
    assert math.isnan(result.ci_low) and math.isnan(result.ci_high)


def test_cluster_bootstrap_as_dict() -> None:
    records = [{"task": "a", "y": 1}, {"task": "b", "y": 0}]
    result = cluster_bootstrap(records, mean_statistic("y"), "task", n_boot=10, seed=3)
    out = result.as_dict()
    assert out["method"] == "cluster percentile bootstrap"
    assert {k: out[k] for k in ("estimate", "n_boot", "n_clusters", "level", "seed")} == {
        "estimate": 0.5,
        "n_boot": 10,
        "n_clusters": 2,
        "level": 0.95,
        "seed": 3,
    }


@pytest.mark.parametrize(
    ("records", "kwargs"),
    [
        ([], {}),
        ([{"task": "a", "y": 1}], {"n_boot": 0}),
        ([{"task": "a", "y": 1}], {"level": 1.0}),
        ([{"task": "a", "y": 1}], {"level": 0.0}),
    ],
)
def test_cluster_bootstrap_rejects_bad_input(
    records: Sequence[Record], kwargs: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        cluster_bootstrap(records, mean_statistic("y"), "task", **kwargs)


# Distinct copies of repeated clusters ------------------------------------------------


def _n_cluster_labels(records: Sequence[Record]) -> float:
    return float(len({r["task"] for r in records}))


def test_relabel_field_labels_each_draw_position() -> None:
    relabel = relabel_field("task")
    record = {"task": "t1", "y": 1}
    assert relabel(record, 3) == {"task": "3:t1", "y": 1}
    assert record == {"task": "t1", "y": 1}  # the input record is not modified
    # The position ends at the first colon, so labels from different positions differ
    # even when the original labels contain colons.
    assert relabel({"task": "2:x"}, 1) != relabel({"task": ":x"}, 12)


def test_relabel_makes_repeated_draws_distinct_clusters() -> None:
    # SYNTHETIC: 5 clusters of 2 records; the statistic counts distinct cluster labels.
    records = [{"task": f"t{c}", "y": c % 2} for c in range(5) for _ in range(2)]
    merged = cluster_bootstrap(records, _n_cluster_labels, "task", n_boot=200, seed=3)
    distinct = cluster_bootstrap(
        records, _n_cluster_labels, "task", n_boot=200, seed=3, relabel=relabel_field("task")
    )
    assert merged.estimate == distinct.estimate == 5.0
    assert merged.ci_low < 5.0  # without relabeling a cluster drawn twice is one cluster
    assert (distinct.ci_low, distinct.ci_high) == (5.0, 5.0)


def test_relabel_does_not_change_a_statistic_that_ignores_labels() -> None:
    records = synthetic_clustered(np.random.default_rng(4), 10, 3, 2.0, 3.0)
    stat = mean_statistic("y")
    plain = cluster_bootstrap(records, stat, "task", n_boot=150, seed=2)
    relabeled = cluster_bootstrap(
        records, stat, "task", n_boot=150, seed=2, relabel=relabel_field("task")
    )
    assert relabeled == plain


# Several statistics from the same replicates -------------------------------------------


def _mean_and_largest_cluster(records: Sequence[Record]) -> dict[str, float]:
    sizes: dict[Any, int] = {}
    for r in records:
        sizes[r["task"]] = sizes.get(r["task"], 0) + 1
    return {
        "mean": mean_statistic("y")(records),
        "max_cluster": float(max(sizes.values())),
    }


def test_cluster_bootstrap_many_equals_one_statistic_at_a_time() -> None:
    records = synthetic_clustered(np.random.default_rng(6), 9, 4, 2.0, 5.0)
    many = cluster_bootstrap_many(
        records, _mean_and_largest_cluster, "task", n_boot=250, seed=5, level=0.9
    )
    assert set(many) == {"mean", "max_cluster"}
    assert many["mean"] == cluster_bootstrap(
        records, mean_statistic("y"), "task", n_boot=250, seed=5, level=0.9
    )
    single = cluster_bootstrap(
        records,
        lambda rows: _mean_and_largest_cluster(rows)["max_cluster"],
        "task",
        n_boot=250,
        seed=5,
        level=0.9,
    )
    assert many["max_cluster"] == single


def test_cluster_bootstrap_many_relabel_and_explicit_names() -> None:
    records = [{"task": f"t{c}", "y": c % 2} for c in range(4) for _ in range(3)]

    def stat(rows: Sequence[Record]) -> dict[str, float]:
        return {"clusters": _n_cluster_labels(rows), "ignored": 1.0}

    out = cluster_bootstrap_many(
        records,
        stat,
        "task",
        n_boot=100,
        seed=1,
        names=["clusters", "absent"],
        relabel=relabel_field("task"),
    )
    assert list(out) == ["clusters", "absent"]
    assert (out["clusters"].ci_low, out["clusters"].ci_high) == (4.0, 4.0)
    # A name the statistic never returns is NaN in every replicate and in the estimate.
    assert math.isnan(out["absent"].estimate) and out["absent"].n_nonfinite == 100
    assert math.isnan(out["absent"].ci_low)


def test_cluster_bootstrap_many_counts_names_missing_from_some_replicates() -> None:
    # SYNTHETIC: "b_mean" exists only when cluster "b" was drawn.
    records = [{"task": "a", "y": 0}, {"task": "b", "y": 1}, {"task": "c", "y": 1}]

    def stat(rows: Sequence[Record]) -> dict[str, float]:
        out = {"mean": mean_statistic("y")(rows)}
        if any(r["task"] == "b" for r in rows):
            out["b_mean"] = 1.0
        return out

    res = cluster_bootstrap_many(records, stat, "task", n_boot=300, seed=8)
    assert res["mean"].n_nonfinite == 0
    assert 0 < res["b_mean"].n_nonfinite < 300
    assert (res["b_mean"].ci_low, res["b_mean"].ci_high) == (1.0, 1.0)


def test_cluster_bootstrap_many_rejects_bad_input() -> None:
    records = [{"task": "a", "y": 1}, {"task": "b", "y": 0}]
    with pytest.raises(ValueError, match="at least one record"):
        cluster_bootstrap_many([], _mean_and_largest_cluster, "task")
    with pytest.raises(ValueError, match="no statistics"):
        cluster_bootstrap_many(records, lambda rows: {}, "task", n_boot=5)
    with pytest.raises(ValueError, match="unique"):
        cluster_bootstrap_many(records, _mean_and_largest_cluster, "task", names=["mean", "mean"])
    with pytest.raises(ValueError, match="n_boot"):
        cluster_bootstrap_many(records, _mean_and_largest_cluster, "task", n_boot=0)


def _mean_y(records: Sequence[Record]) -> float:
    return float(sum(r["y"] for r in records)) / len(records)


def _coverage(n_datasets: int, n_boot: int, seed: int) -> float:
    """Share of synthetic datasets whose 95% interval covers the true rate 0.3."""
    rng = np.random.default_rng(seed)
    covered = 0
    for d in range(n_datasets):
        # Cluster rates from Beta(3, 7), whose mean is exactly 0.3, equal cluster sizes.
        records = synthetic_clustered(rng, 30, 8, 3.0, 7.0)
        res = cluster_bootstrap(records, _mean_y, "task", n_boot=n_boot, seed=d)
        covered += res.ci_low <= 0.3 <= res.ci_high
    return covered / n_datasets


def test_cluster_bootstrap_coverage_small_simulation() -> None:
    # 200 synthetic datasets: Monte Carlo SD of the coverage is about 0.017.
    assert 0.89 <= _coverage(200, 300, seed=20261104) <= 0.99


@pytest.mark.slow
def test_cluster_bootstrap_coverage_larger_simulation() -> None:
    # 1000 synthetic datasets: Monte Carlo SD of the coverage is about 0.008. Percentile
    # intervals under-cover slightly with 30 clusters, so the band sits below 0.95.
    assert 0.90 <= _coverage(1000, 1000, seed=5) <= 0.97


# Paired cluster bootstrap -------------------------------------------------------


def synthetic_paired(rng: np.random.Generator, n_tasks: int, shift: float) -> list[dict[str, Any]]:
    """Synthetic records with a control and a treatment arm inside each task."""
    records: list[dict[str, Any]] = []
    for t in range(n_tasks):
        base = rng.uniform(0.1, 0.6)
        for arm, p in (("control", base), ("treatment", min(1.0, base + shift))):
            for _ in range(4):
                records.append({"task": t, "arm": arm, "y": int(rng.random() < p)})
    return records


def test_paired_bootstrap_estimate_and_reproducibility() -> None:
    records = synthetic_paired(np.random.default_rng(9), 20, 0.25)
    stat = mean_statistic("y")
    res = paired_cluster_bootstrap(
        records, stat, "task", "arm", "treatment", "control", n_boot=300, seed=1
    )
    treat = [r for r in records if r["arm"] == "treatment"]
    ctrl = [r for r in records if r["arm"] == "control"]
    assert isinstance(res, PairedBootstrapResult)
    assert res.treatment_estimate == pytest.approx(stat(treat))
    assert res.control_estimate == pytest.approx(stat(ctrl))
    assert res.estimate == pytest.approx(stat(treat) - stat(ctrl))
    assert res.ci_low <= res.estimate <= res.ci_high
    assert res.n_clusters == 20 and res.n_unpaired_clusters == 0
    again = paired_cluster_bootstrap(
        records, stat, "task", "arm", "treatment", "control", n_boot=300, seed=1
    )
    assert again == res
    out = res.as_dict()
    assert out["treatment_estimate"] == res.treatment_estimate
    assert out["n_unpaired_clusters"] == 0


def test_paired_bootstrap_keeps_pairs_together() -> None:
    # Within every task the two arms are identical, so every paired replicate
    # difference is exactly 0; independent resampling of arms would not give that.
    records: list[dict[str, Any]] = []
    for t, v in enumerate([0, 1, 1, 0, 1, 0, 0, 1]):
        for arm in ("control", "treatment"):
            records.append({"task": t, "arm": arm, "y": v})
    res = paired_cluster_bootstrap(
        records, mean_statistic("y"), "task", "arm", "treatment", "control", n_boot=200
    )
    assert (res.ci_low, res.estimate, res.ci_high) == (0.0, 0.0, 0.0)


def test_paired_bootstrap_drops_unpaired_clusters_and_other_arms() -> None:
    records = [
        {"task": "a", "arm": "control", "y": 0},
        {"task": "a", "arm": "treatment", "y": 1},
        {"task": "b", "arm": "control", "y": 0},
        {"task": "c", "arm": "treatment", "y": 1},
        {"task": "a", "arm": "other", "y": 1},
    ]
    res = paired_cluster_bootstrap(
        records, mean_statistic("y"), "task", "arm", "treatment", "control", n_boot=50
    )
    assert res.n_clusters == 1 and res.n_unpaired_clusters == 2
    assert res.estimate == 1.0


def test_paired_bootstrap_relabels_both_arms_of_a_drawn_cluster() -> None:
    # SYNTHETIC: 6 tasks with both arms. With relabeling, every replicate has 6 distinct
    # treatment clusters and 6 distinct control clusters, so the difference is always 0.
    records = [{"task": t, "arm": arm, "y": t % 2} for t in range(6) for arm in ("c", "t")]
    plain = paired_cluster_bootstrap(
        records, _n_cluster_labels, "task", "arm", "t", "c", n_boot=100, seed=2
    )
    relabeled = paired_cluster_bootstrap(
        records,
        _n_cluster_labels,
        "task",
        "arm",
        "t",
        "c",
        n_boot=100,
        seed=2,
        relabel=relabel_field("task"),
    )
    assert plain.estimate == relabeled.estimate == 0.0
    assert relabeled.treatment_estimate == relabeled.control_estimate == 6.0
    assert (relabeled.ci_low, relabeled.ci_high) == (0.0, 0.0)
    calls: list[set[Any]] = []

    def labels(rows: Sequence[Record]) -> float:
        calls.append({r["task"] for r in rows})
        return 0.0

    paired_cluster_bootstrap(
        records, labels, "task", "arm", "t", "c", n_boot=3, seed=2, relabel=relabel_field("task")
    )
    # Every call sees 6 distinct clusters; the replicate calls (two per replicate, one
    # per arm) see position-prefixed labels, the two estimate calls the original ones.
    assert all(len(found) == 6 for found in calls)
    prefixed = [found for found in calls if all(":" in str(label) for label in found)]
    assert len(prefixed) == 2 * 3 and len(calls) == 2 * 3 + 2


def test_paired_bootstrap_rejects_bad_input() -> None:
    stat = mean_statistic("y")
    only_control = [{"task": "a", "arm": "control", "y": 0}]
    with pytest.raises(ValueError, match="both"):
        paired_cluster_bootstrap(only_control, stat, "task", "arm", "treatment", "control")
    with pytest.raises(ValueError, match="differ"):
        paired_cluster_bootstrap(only_control, stat, "task", "arm", "control", "control")
    with pytest.raises(ValueError):
        paired_cluster_bootstrap(
            only_control, stat, "task", "arm", "treatment", "control", n_boot=0
        )
