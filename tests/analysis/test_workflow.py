"""End-to-end use of receipts.analysis on SYNTHETIC E1-like records.

The run records are generated here from known parameters and passed through
``receipts.study.aggregate.e1_rows`` and a JSONL round trip, so the analysis sees
rows in the exact shape of ``artifacts/e1/runs.jsonl`` (manipulation levels nested
under ``conditions``). They are not agent runs and nothing computed here is a study
result.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.special import expit

import receipts.analysis as analysis
from receipts.analysis import (
    Formula,
    bootstrap_coefficients,
    build_design,
    cluster_bootstrap,
    fit_glmm,
    flatten_records,
    holm_bonferroni,
    likelihood_ratio_test,
    mean_statistic,
    odds_ratio,
    paired_cluster_bootstrap,
    rate_with_ci,
    treatment_column,
)
from receipts.study.aggregate import e1_rows, write_jsonl
from receipts.study.plan import half_fraction_cells
from receipts.study.spec import CONDITION_LEVELS

ARMS = ("ma-qwen7b", "ma-qwen1.5b", "ma-granite8b", "ma-granite2b")
FAMILY = {"ma-qwen7b": "qwen", "ma-qwen1.5b": "qwen", "ma-granite8b": "granite"}
FAMILY["ma-granite2b"] = "granite"
#: SYNTHETIC design parameters (log-odds), not estimates of anything.
MANIPULATION_EFFECT = {"M1": 1.0, "M2": 0.6, "M3": 0.0, "M4": -0.5, "M5": 0.3}
ARM_EFFECT = {"ma-qwen7b": 0.0, "ma-qwen1.5b": 0.5, "ma-granite8b": -0.3, "ma-granite2b": 0.8}
#: Every NO_REPORT-th run ends without a final report (SYNTHETIC), so it is excluded.
NO_REPORT = 29


def synthetic_run_records(seed: int, n_tasks: int, replicates: int) -> list[dict[str, Any]]:
    """SYNTHETIC run records with the ``run.json`` fields that ``e1_rows`` reads.

    The 16 half-fraction cells times ``replicates``, identical work in every arm.
    False success follows a random-intercept logistic model with the parameters above;
    a run without a report has no claims and no success report. Every record carries
    ``synthetic: True``.
    """
    rng = np.random.default_rng(seed)
    task_effect = rng.normal(0.0, 0.8, n_tasks)
    cells = half_fraction_cells() * replicates
    tasks = rng.permutation(np.arange(len(cells)) % n_tasks)
    records = []
    for arm in ARMS:
        for i, (task, cell) in enumerate(zip(tasks, cells, strict=True)):
            eta = -1.2 + ARM_EFFECT[arm] + task_effect[task]
            eta += sum(
                MANIPULATION_EFFECT[f]
                for f, level in cell.items()
                if level != CONDITION_LEVELS[f][0]
            )
            reported = i % NO_REPORT != 0
            false_success = reported and bool(rng.random() < float(expit(eta)))
            ground_truth = not false_success and bool(rng.random() < 0.5)
            verdict = "contradicted" if false_success else "supported"
            records.append(
                {
                    "run_id": f"synthetic-{i:03d}-{arm}",
                    "task_id": f"task{task:02d}",
                    "config_id": arm,
                    "model": f"synthetic-{arm}",
                    "family": FAMILY[arm],
                    "conditions": dict(cell),
                    "seed": i,
                    "report": "SYNTHETIC report: all tests pass." if reported else "",
                    "stop_reason": "finished" if reported else "turn_cap",
                    "success_reported": reported and (false_success or ground_truth),
                    "ground_truth_success": ground_truth,
                    "false_success": false_success,
                    "claims": [{"claim_id": "c1", "type": "tests_pass", "verdict": verdict}]
                    if reported
                    else [],
                    "omissions": 0,
                    "synthetic": True,
                }
            )
    return records


def synthetic_e1(seed: int, n_tasks: int, replicates: int) -> list[dict[str, Any]]:
    """SYNTHETIC rows in the shape of ``artifacts/e1/runs.jsonl``, built by ``e1_rows``.

    ``e1_rows`` copies each run record's ``synthetic`` flag, so every row says it is
    synthetic (the test checks this after the JSONL round trip).
    """
    return e1_rows(synthetic_run_records(seed, n_tasks, replicates))


def test_package_exports_resolve() -> None:
    for name in analysis.__all__:
        assert getattr(analysis, name) is not None


def test_e1_style_analysis_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    write_jsonl(path, synthetic_e1(seed=20261104, n_tasks=24, replicates=8))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(r["synthetic"] is True for r in rows)
    assert all("M1" not in r and set(r["conditions"]) == set(CONDITION_LEVELS) for r in rows)
    reference = {f: levels[0] for f, levels in CONDITION_LEVELS.items()}
    formula = Formula(
        response="false_success",
        factors=("config_id", *CONDITION_LEVELS),
        reference={"config_id": "ma-qwen7b", **reference},
        group="task_id",
    )
    # The banked rows nest the conditions; the error says how to reach them.
    with pytest.raises(ValueError, match="flatten_records"):
        build_design(rows, formula)
    # Y1 is analyzed among runs with a non-empty final report (prereg 0001 section 5).
    included = flatten_records([r for r in rows if r["included"]])
    assert len(included) == len(rows) - 4 * 5  # 5 runs per arm without a report
    design = build_design(included, formula)
    assert design.n_obs == len(included) and design.n_groups == 24
    fit = fit_glmm(design, n_agq=8)
    assert fit.converged and not fit.separation

    # Manipulation effects, as odds ratios, near the synthetic truth.
    contrasts = {
        f: odds_ratio(fit, treatment_column(f, CONDITION_LEVELS[f][1])) for f in CONDITION_LEVELS
    }
    for f, c in contrasts.items():
        assert abs(c.estimate - MANIPULATION_EFFECT[f]) < 4 * c.se
        assert c.or_ci_low < c.odds_ratio < c.or_ci_high

    # The preregistered family (here one outcome x five manipulations), Holm-adjusted.
    holm = holm_bonferroni([c.p_value for c in contrasts.values()])
    assert holm.reject[0]  # M1, the largest synthetic effect
    assert not holm.reject[2]  # M3, a synthetic effect of exactly 0

    # The arm factor: likelihood-ratio test with 3 degrees of freedom.
    no_arm = build_design(
        included,
        Formula("false_success", tuple(CONDITION_LEVELS), reference=reference, group="task_id"),
    )
    arm_test = likelihood_ratio_test(fit_glmm(no_arm, n_agq=8), fit)
    assert arm_test.df == 3 and not arm_test.boundary
    assert arm_test.p_value < 0.05

    # Robustness check: task-bootstrap intervals for the effects (few replicates here
    # to keep the test fast; the preregistration asks for 2000).
    effect_boot = bootstrap_coefficients(included, formula, n_agq=8, n_boot=15, seed=20261104)
    assert list(effect_boot) == list(fit.column_names)
    for c in contrasts.values():
        b = effect_boot[c.name]
        assert b.estimate == pytest.approx(c.estimate, abs=1e-9)
        assert b.n_nonfinite == 0 and b.n_clusters == 24
        assert b.ci_low < c.estimate < b.ci_high

    # RQ1-style prevalence for one arm: Wilson and task-cluster bootstrap intervals,
    # on the same included rows that tools/ship_check.py recomputes the rate from.
    arm_rows = [r for r in included if r["config_id"] == "ma-qwen7b"]
    k = sum(r["false_success"] for r in arm_rows)
    wilson = rate_with_ci(k, len(arm_rows))
    boot = cluster_bootstrap(arm_rows, mean_statistic("false_success"), "task_id", seed=20261104)
    assert boot.estimate == pytest.approx(wilson.estimate)
    assert boot.ci_high - boot.ci_low > 0

    # A flattened condition is an ordinary field: M1's rate difference within tasks.
    m1 = paired_cluster_bootstrap(
        included,
        mean_statistic("false_success"),
        "task_id",
        "M1",
        "unattainable",
        "attainable",
        n_boot=200,
        seed=20261104,
    )
    # The shuffle balances tasks over cells, not M1 levels within each task.
    assert m1.n_clusters + m1.n_unpaired_clusters == 24
    assert m1.ci_low < m1.estimate < m1.ci_high
    assert m1.estimate > 0  # the synthetic M1 effect is +1.0 log-odds

    # Everything banks as JSON.
    banked = {
        "synthetic": True,
        "fit": fit.as_dict(),
        "contrasts": {f: c.as_dict() for f, c in contrasts.items()},
        "effect_bootstrap": {name: b.as_dict() for name, b in effect_boot.items()},
        "holm": holm.as_dict(),
        "arm_lrt": vars(arm_test),
        "rate": {"wilson": wilson.as_dict(), "bootstrap": boot.as_dict()},
        "m1_paired": m1.as_dict(),
    }
    text = json.dumps(banked, allow_nan=False)
    assert math.isfinite(json.loads(text)["fit"]["log_likelihood"])
