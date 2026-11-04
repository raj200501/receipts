"""Statistical analysis for the preregistered study (docs/BUILD_BRIEF.md sections 3 and 5).

- :mod:`receipts.analysis.rates`: Wilson score intervals, and percentile intervals from
  a bootstrap that resamples tasks (clusters), for one statistic, for several computed
  together, and paired for two conditions run on the same tasks.
- :mod:`receipts.analysis.design`: treatment-coded design matrices from records, with
  optional two-way interactions and task clusters, and :func:`flatten_records` for
  rows whose manipulation levels sit in a nested ``conditions`` mapping (the rows of
  ``artifacts/e1/runs.jsonl``).
- :mod:`receipts.analysis.glmm`: logistic regression with a random intercept per task,
  fitted by maximum likelihood with adaptive Gauss-Hermite quadrature; plain logistic
  regression; likelihood-ratio tests; separation checks; task-bootstrap intervals for
  the coefficients.
- :mod:`receipts.analysis.contrasts`: linear contrasts, odds ratios, joint Wald tests,
  and Holm-Bonferroni adjustment.
- :mod:`receipts.analysis.power`: simulation power analysis for factorial designs and
  a search for the smallest sufficient design size (all simulated data is synthetic
  and labeled so).
"""

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
from receipts.analysis.design import (
    INTERCEPT,
    Design,
    Formula,
    build_design,
    flatten_records,
    interaction_column,
    treatment_column,
)
from receipts.analysis.glmm import (
    Coefficient,
    FitResult,
    LikelihoodRatioTest,
    SeparationCheck,
    bootstrap_coefficients,
    detect_separation,
    fit_glmm,
    fit_logistic,
    likelihood_ratio_test,
    marginal_log_likelihood,
    marginal_score,
)
from receipts.analysis.power import (
    EffectPower,
    PowerResult,
    SampleSizeSearch,
    full_factorial,
    half_fraction,
    simulate_power,
    smallest_sufficient,
)
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

__all__ = [
    "INTERCEPT",
    "Z95",
    "BootstrapResult",
    "Coefficient",
    "Contrast",
    "Design",
    "EffectPower",
    "FitResult",
    "Formula",
    "HolmResult",
    "LikelihoodRatioTest",
    "PairedBootstrapResult",
    "PowerResult",
    "RateCI",
    "SampleSizeSearch",
    "SeparationCheck",
    "WaldTest",
    "bootstrap_coefficients",
    "build_design",
    "cluster_bootstrap",
    "cluster_bootstrap_many",
    "contrast_vector",
    "detect_separation",
    "fit_glmm",
    "fit_logistic",
    "flatten_records",
    "full_factorial",
    "half_fraction",
    "holm_bonferroni",
    "interaction_column",
    "likelihood_ratio_test",
    "linear_contrast",
    "marginal_log_likelihood",
    "marginal_score",
    "mean_statistic",
    "odds_ratio",
    "paired_cluster_bootstrap",
    "rate_with_ci",
    "ratio_statistic",
    "relabel_field",
    "simulate_power",
    "smallest_sufficient",
    "treatment_column",
    "wald_test",
    "wilson_interval",
]
