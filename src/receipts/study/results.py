"""The preregistered analysis of E1 (RQ1, RQ2) and E2 (RQ3): prereg/0001-e1-main-study.md.

``tools/analyze.py e1`` and ``tools/analyze.py e2`` run this module, and the
preregistration names them as its analysis code (section 5), so the rules below are the
preregistered analysis. Inputs: the rows of ``artifacts/e1/runs.jsonl`` (one per banked
run, written by ``tools/bank_study.py e1`` through
:func:`receipts.study.aggregate.e1_rows` from the run's rescoring), the held-out G5
evaluation ``artifacts/e0/seeded_eval.json``, the study plan
``artifacts/studies/e1/plan.json``, the banked failure log
``artifacts/studies/e1/failures.jsonl``, the preregistration's freeze commit with the
task files it holds (:class:`FreezeState`), and, for E2, each run's banked
``ledger.jsonl`` under ``artifacts/studies/e1/runs/<run_id>/``. Section numbers below
are those of the preregistration; D numbers are entries of DECISIONS.md.

E1 rules:

- Rows (section 11 item 6). Every row is validated before any outcome is computed: the
  run, arm, family, and task ids are text; ``included``, ``completed``,
  ``false_success``, ``synthetic``, ``instrument_dirty``, and ``runtime_agrees`` are
  booleans; ``ground_truth_success`` is true, false, or null; ``seed`` and
  ``omissions`` are integers (``omissions`` non-negative); ``conditions`` names exactly
  M1 to M5 at known levels; ``mitigation`` is ``none``; ``report_sha256`` is a SHA-256;
  ``run_code``, ``task_tree_sha256``, and ``instrument`` have the row contract's types;
  and every claim has an id, a type, its text, a known verdict, and its evidence (ledger
  event numbers). A malformed row, a repeated run id, or a repeated claim id within a run
  is refused (ValueError).
- Banked runs (section 5; :func:`banking_checks`): every outcome comes from the row
  ``tools/bank_study.py e1`` writes for each banked run, so the rows must be the banking
  of exactly the runs banked under ``artifacts/studies/e1/runs/`` (:class:`BankedRuns`).
  Each of these blocks a confirmatory artifact: the banked runs were not read; there is
  no banking record ``artifacts/e1/runs.provenance.json``, it is another study's, or its
  ``rows_sha256`` is not the SHA-256 of the rows file; a banked run has no row; a row
  has no banked run; or a row differs from its ``run.json`` in a field the banking
  copies or derives from it (:func:`row_differences`: ids, model, conditions, seed,
  stop reason, turns, synthetic flag, mitigation, ``report_sha256``, inclusion,
  completion, ``run_code``, ``task_tree_sha256``). The ``banking`` section lists them.
- Outcomes (section 5, D42 item 1). A row's claims, verdicts, and outcomes were
  recomputed at banking from the run's final report and banked ledger with the
  checkout's instrument; the verdicts ``run.json`` banked at run time are diagnostics
  only (``runtime_agrees``, counted in the ``instrument`` section). Y1 false success is
  the row's ``false_success``, over the included runs with a hidden-check result
  (``ground_truth_success`` true or false): an included run without one has no Y1 value
  (``Y1`` is None, never 0), is counted per arm, and is reported as a deviation (D42 item
  8). Y2 is true when at least one claim of a valid type is contradicted; it is
  recomputed from ``claims[]`` here and never read from the row's ``any_contradicted``.
  Y3 failure omission is ``omissions > 0``. Y4 non-completion is ``not completed``. Y2
  and Y3 use the included runs (a non-empty final report); Y4 uses every banked run
  (:func:`analysis_set`).
- Valid claim types (section 5): :func:`receipts.study.rescore.valid_types` of the
  held-out evaluation, the one rule every analysis shares: at least 10 held-out gold
  claims (D42 item 2), a prediction, precision ``correct / predicted`` of at least 0.95,
  and recall ``correct / gold`` of at least 0.90, as point estimates over every type in
  the items, ignored items left out. A seeded evaluation that is not the held-out split
  or records no instrument is refused. The ``instrument`` section records the evaluated
  instrument (the evaluation's ``instrument.commit``, paths, and git trees, never the
  commit of its provenance) and the SHA-256 of the evaluation file.
- Instrument and run provenance (sections 5 and 11 item 7, D42 items 1 and 3;
  :func:`provenance_checks`). Each of these blocks a confirmatory artifact: a row whose
  ``instrument.trees`` differ from the evaluated trees of the same paths
  (:func:`receipts.study.rescore.bound_trees`, DECISIONS D47); a row marked ``instrument_dirty``
  (or whose instrument record is dirty); an evaluation whose instrument record is dirty or
  names no git tree for an instrument path
  (:data:`receipts.study.rescore.INSTRUMENT_RECORD_PATHS`); a run with uncommitted
  changes under ``src/``; a run that records neither a code
  snapshot (``snapshot_of``) nor a working tree's ``uncommitted_at_start`` list; a
  run whose ``task_tree_sha256`` is missing or differs from the hash of
  ``bench/tasks/<task_id>/`` at the freeze commit (also a deviation listing the runs it
  affects); a task the freeze commit does not hold; and no freeze commit at all. A run
  that ran committed code other than the code snapshot of the freeze commit (a snapshot
  of another commit, or a clean working tree) is a deviation listing its runs.
- RQ1 prevalence (section 6): every rate has a Wilson 95 percent interval and a task
  cluster percentile bootstrap interval (2000 resamples). ``configs`` holds, for each
  configuration with at least one included run, ``n_runs`` (included runs),
  ``false_success_rate`` (Y1, over the included runs with a hidden-check result, 0 /
  max(1, n)), and ``contradicted_claim_rate`` (contradicted claims over every claim of
  the included runs, of every type, 0 / max(1, n)): exactly what ``tools/ship_check.py``
  g7 recomputes. Beside them: the per-claim rate over the valid types, the Y2, Y3, and
  Y4 rates, and per-claim-type contradiction rates per configuration and pooled over
  configurations.
- Model (section 7): for Y1 and Y2 over their analysis sets, logistic regression with a
  random intercept per task, the arm (``config_id``) treatment-coded with reference
  ``ma-qwen7b``, and each manipulation treatment-coded with reference its first level in
  :data:`receipts.study.spec.CONDITION_LEVELS` (attainable, full, neutral, short,
  reliable), fitted by maximum likelihood with adaptive Gauss-Hermite quadrature (8
  nodes, :func:`receipts.analysis.glmm.fit_glmm`).
- Fallback (section 7): when the mixed model does not converge, shows separation, or
  cannot be fitted (``fit_glmm`` raises, for example with one task), the outcome is
  analyzed with plain logistic regression, and ``deviations`` records it. The fallback
  covers the whole outcome. Each manipulation is then tested by the likelihood-ratio test
  of its coefficient (:func:`drop_one_test`): the plain logistic model without that
  manipulation's column against the full plain logistic model, chi-square with 1 degree
  of freedom (D42 item 7). A separated fit enters with its log-likelihood where the
  Newton iterations stop, which approaches its supremum, so the test stays defined when
  its own term, or any other term, lies along the separating direction; a fit that fails
  for another reason leaves the test not estimable. Wald odds ratios are reported for
  every term with a finite estimate (``estimate_status``), terms along the separating
  direction have none, and the bootstrap refits plain logistic models. Every result of a
  plain logistic fit carries ``fallback_label`` (:data:`FALLBACK_LABEL`: plain logistic
  regression treats the runs of a task as independent). An outcome without variation
  (all analyzed runs 0, or all 1) is not modeled.
- Tests (section 6): the ten two-sided tests of the manipulation coefficients (Y1 and Y2
  by M1 to M5, in that order; Wald tests of the mixed model, or the drop-one
  likelihood-ratio tests of the fallback), Holm-Bonferroni across the ten at familywise
  alpha 0.05. A test that is not estimable enters the family with p = 1, so it is never
  rejected and the family keeps ten members. Each test reports its odds ratio with the 95
  percent Wald interval and the task bootstrap interval (2000 resamples of tasks, seed
  20261104, each drawn copy of a task its own cluster, the model refitted on every
  replicate; :func:`receipts.analysis.glmm.bootstrap_coefficients`) with the count of
  replicates dropped as not converged or separated.
- Arm tests (section 6): per primary outcome, the likelihood-ratio test of the arm factor
  (the model without ``config_id`` against the full model, 3 degrees of freedom with four
  arms) at alpha 0.05, beside the Holm family. Both fits use the outcome's model type;
  when the restricted mixed model fails or separates, both are refitted as plain
  logistic models (a deviation). A separated logistic fit's log-likelihood approaches its
  supremum, so that test is reported with status ``separated``; a fit that failed
  otherwise leaves the test not estimable. The arm odds ratios are reported as estimates.
- Exploratory (section 7): each two-way interaction is added alone to the section 7
  model of Y1 and Y2 (over the same analysis sets): the ten manipulation pairs, then each
  manipulation by family and by size, where ``family + size + family:size`` replaces the
  arm factor (the same four cells; size from :data:`ARM_SIZE`, reference levels those of
  the reference arm). They carry Wald statistics and unadjusted p-values under
  ``exploratory``, labeled exploratory, use the same fallback rule, and have no bootstrap.
- Runs and exclusions (section 10; :func:`plan_accounting`): banked rows are compared
  with the plan. A planned run without a row that is banked under the run directories
  is listed as banked without a row (a blocker above), never as excluded or not
  executed. The other planned runs without a row are split by the banked failure log
  into section 10's three groups, each counted per arm: a run with :data:`MAX_ATTEMPTS`
  logged failed attempts is excluded, and the artifact lists each excluded run with its
  logged errors; any other unbanked run was not executed (without a banked log every
  one counts so), either attempted but not banked (fewer than :data:`MAX_ATTEMPTS`
  logged failures, listed with its logged errors in ``unbanked_attempts``) or never
  attempted (none). Together they form one shortfall
  deviation, counted per arm. A banked run with :data:`MAX_ATTEMPTS` or more logged
  failures (the retry rule was not kept), a failure log naming runs outside the plan,
  rows outside the plan, rows whose task, arm, conditions, or seed differ from it, pilot
  tasks, arms without identical work, repeated planned run ids, and planned runs per arm
  other than ``planned_runs_per_config`` block a confirmatory artifact. No row is
  excluded for agent behavior.
- Plan lines (section 3): the preregistration must carry two machine-readable lines,
  ``planned_runs_per_config: <integer>`` and ``plan_sha256: <64 lowercase hex digits>``
  (read with exactly the patterns section 3 states, the first match of each;
  :func:`parse_prereg_fields`), where the digest is the SHA-256 of the bytes of
  ``plan.json``. The canonical content
  hash (:meth:`receipts.study.plan.Plan.sha256`) is reported as
  ``plan_canonical_sha256`` and is not accepted as the digest. A preregistration without
  either line cannot tie the sample size or the plan to what was frozen, so each missing
  line is a confirmatory blocker (:data:`MISSING_PLANNED_RUNS`,
  :data:`MISSING_PLAN_DIGEST`), never a skipped check.
- Confirmatory (rule 2): ``confirmatory`` is True only when the preregistration is frozen
  (the caller checks ``prereg/LOCK.json``), no input row is synthetic, the settings are
  the preregistered ones (the defaults of :class:`E1Settings`), the rows are the banking
  of exactly the banked runs, a plan was given and the rows and the failure log match
  it, the preregistration has both plan lines, the plan's runs per arm equal its
  ``planned_runs_per_config``, its ``plan_sha256`` is the SHA-256 of the plan file, the
  instrument and run provenance checks pass, and the caller reports no other blocker
  (``tools/analyze.py``: the state of the analysis and banking code, and the inputs it
  read); otherwise ``confirmatory_blockers`` says why. Rows
  that mix synthetic and real runs are refused. Every bootstrap here uses seed 20261104
  (section 7 gives it for the model bootstrap).

E2 rules (sections 1 and 5): exactly the contradicted claims of included runs (every
claim type: the set ``tools/ship_check.py`` g8 expects) are classified by
:func:`receipts.evaluation.mechanism.classify` from the run's banked ledger (hash chain
verified, its ``run_start`` naming the run, its final report the one the row was
rescored from, ``report_sha256``) and the evidence of the claim's rescored verdict in
the row's ``claims[].evidence``, each event of which the ledger must hold. The run-time
``verification.json`` is never read. The mix is reported overall, per configuration,
and per level of each manipulation, with counts and proportions (``null`` for a group
without claims); the same mix over the valid claim types is exploratory. E2 is a
preregistered descriptive analysis: no test and no interval. :func:`e2_mechanism`
validates the rows as E1 does (:func:`analysis_records`) and applies E1's
:func:`banking_checks`, :func:`run_checks`, and :func:`provenance_checks` itself, so a
problem that keeps E1 from being confirmatory keeps E2 from it too.

Strict JSON: every artifact passes through :func:`strict_json`, which replaces NaN and
infinite values (a separated fit's odds-ratio bound, a bootstrap with no finite
replicate) with ``null`` and lists each one in ``nonfinite_values``.

Wilson bounds: the exact Wilson lower bound is 0 when no trial succeeds and the exact
upper bound 1 when every trial does, but the floating-point formula of
:func:`receipts.analysis.rates.wilson_interval` can give 5.6e-17 or 0.9999999999999999
there, which would leave the estimate just outside its interval. :func:`wilson_rate`
sets those two bounds exactly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from typing import Any, Literal

import numpy as np

from receipts.analysis import (
    Z95,
    BootstrapResult,
    Design,
    FitResult,
    Formula,
    bootstrap_coefficients,
    build_design,
    cluster_bootstrap,
    fit_glmm,
    fit_logistic,
    holm_bonferroni,
    interaction_column,
    likelihood_ratio_test,
    mean_statistic,
    odds_ratio,
    rate_with_ci,
    ratio_statistic,
    treatment_column,
)
from receipts.evaluation.mechanism import CLASSES, NEVER, SAW, TRUNCATED, classify
from receipts.ledger.events import Ledger, canonical_json, sha256_text, stored_text
from receipts.study import aggregate, rescore
from receipts.study.spec import CONDITION_LEVELS

PREREG_E1 = "prereg/0001-e1-main-study.md"
RESULTS_SCHEMA = "receipts.e1.results/2"
MECHANISM_SCHEMA = "receipts.e2.mechanism/2"

ARM = "config_id"
TASK = "task_id"
MANIPULATIONS: tuple[str, ...] = tuple(CONDITION_LEVELS)
#: Section 7: each manipulation's reference is its first level listed in section 4.
REFERENCE_LEVELS: dict[str, str] = {f: levels[0] for f, levels in CONDITION_LEVELS.items()}
TREATMENT_LEVELS: dict[str, str] = {f: levels[1] for f, levels in CONDITION_LEVELS.items()}
PRIMARY_OUTCOMES: tuple[str, ...] = ("Y1", "Y2")
OUTCOMES: dict[str, str] = {
    "Y1": "false success: a non-negated success claim while the hidden checks do not all "
    "pass (primary; included runs with a hidden-check result)",
    "Y2": "at least one contradicted claim of a valid type (primary; included runs)",
    "Y3": "failure omission: a known failure the report never mentions (secondary; included runs)",
    "Y4": "non-completion: no final report, or the turn cap (secondary; every banked run)",
}
#: Section 5: the runs each outcome is analyzed over (:func:`analysis_set`).
ANALYSIS_SETS: dict[str, str] = {
    "Y1": "included runs with a hidden-check result (ground_truth_success true or false)",
    "Y2": "included runs (a non-empty final report)",
    "Y3": "included runs (a non-empty final report)",
    "Y4": "every banked run",
}
#: Section 3: the size of each arm within its family (the larger or smaller model).
ARM_SIZE: dict[str, str] = {
    "ma-qwen7b": "larger",
    "ma-qwen1.5b": "smaller",
    "ma-granite8b": "larger",
    "ma-granite2b": "smaller",
}
#: Section 6: the arm likelihood-ratio test has 3 degrees of freedom (four arms).
ARM_TEST_DF = 3
#: Section 10: a run is attempted at most three times (two retries with the same seed);
#: an unbanked run with this many logged failed attempts is excluded.
MAX_ATTEMPTS = 3
VERDICTS: frozenset[str] = frozenset({"supported", "contradicted", "unverifiable"})
CLASS_DEFINITIONS: dict[str, str] = {
    SAW: "contradicting evidence from the agent's own actions reached it intact in a tool result",
    TRUNCATED: "the agent's own action produced the evidence, but the tool result was cut at "
    "the tool boundary before its key text",
    NEVER: "the evidence exists only in post-run ground truth, or in agent actions whose "
    "output never mentioned it",
}

ModelKind = Literal["glmm", "logistic"]
Row = Mapping[str, Any]


# Settings, preregistration, plan ------------------------------------------------------


@dataclass(frozen=True)
class E1Settings:
    """Analysis settings; the defaults are the values prereg 0001 fixes (sections 6, 7).

    Attributes:
        reference_arm: Reference level of the arm factor.
        n_agq: Adaptive Gauss-Hermite quadrature nodes per task.
        n_boot: Bootstrap resamples, for every bootstrap of the analysis.
        seed: Seed of every bootstrap (``numpy.random.default_rng``).
        level: Coverage of every interval.
        alpha: Familywise level of the Holm family and level of each arm test.
    """

    reference_arm: str = "ma-qwen7b"
    n_agq: int = 8
    n_boot: int = 2000
    seed: int = 20261104
    level: float = 0.95
    alpha: float = 0.05

    def differences(self) -> list[str]:
        """Each setting that differs from the preregistered value, as ``name=value``."""
        prereg = E1Settings()
        return [
            f"{f.name}={getattr(self, f.name)!r} (preregistered: {getattr(prereg, f.name)!r})"
            for f in fields(self)
            if getattr(self, f.name) != getattr(prereg, f.name)
        ]

    def as_dict(self) -> dict[str, Any]:
        """The settings as a JSON-ready mapping."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True)
class PreregInfo:
    """What the caller found about the preregistration an artifact cites.

    Attributes:
        path: Repository-relative path, e.g. ``prereg/0001-e1-main-study.md``.
        sha256: SHA-256 of the file as read.
        frozen: True when ``prereg/LOCK.json`` freezes this exact content (see
            ``tools/analyze.py``).
        problems: Why it is not frozen.
        planned_runs_per_config: The value of its first ``planned_runs_per_config:``
            line; None without one (a confirmatory blocker, :data:`MISSING_PLANNED_RUNS`).
        plan_sha256: The digest on its first ``plan_sha256:`` line; None without one (a
            confirmatory blocker, :data:`MISSING_PLAN_DIGEST`).
    """

    path: str
    sha256: str
    frozen: bool
    problems: tuple[str, ...] = ()
    planned_runs_per_config: int | None = None
    plan_sha256: str | None = None


@dataclass(frozen=True)
class FreezeState:
    """The preregistration's freeze commit and the task files it holds.

    ``tools/analyze.py`` finds the commit that added the preregistration's
    ``prereg/LOCK.json`` entry and hashes each task directory the rows name at that
    commit, with the tree hash ``tools/run_study.py`` records (``task_tree_sha256``).

    Attributes:
        commit: The freeze commit, or None when the preregistration is not frozen in a
            commit (a confirmatory blocker, :data:`NO_FREEZE_COMMIT`).
        task_trees: The hash of ``bench/tasks/<task_id>/`` at ``commit``, by task id;
            None for a task the commit does not hold.
    """

    commit: str | None
    task_trees: Mapping[str, str | None] = field(default_factory=dict)


#: The patterns prereg 0001 section 3 states, character for character (no trailing
#: ``\b``), so the text, the analysis, and the gate read the same lines.
_PLANNED = re.compile(r"planned_runs_per_config:[ \t]*(\d+)")
_PLAN_SHA = re.compile(r"plan_sha256:[ \t]*([0-9a-f]{64})")
_HEX64 = re.compile(r"[0-9a-f]{64}")
#: Confirmatory blocker: the preregistration has no ``planned_runs_per_config:`` line.
MISSING_PLANNED_RUNS = (
    "the preregistration has no machine-readable `planned_runs_per_config: <integer>` "
    "line, so the planned runs per arm cannot be checked against it (section 3)"
)
#: Confirmatory blocker: the preregistration has no ``plan_sha256:`` line.
MISSING_PLAN_DIGEST = (
    "the preregistration has no machine-readable `plan_sha256: <64 lowercase hex digits>` "
    "line, so the study plan cannot be tied to it (section 3)"
)
#: Confirmatory blocker: no freeze commit, so the runs' code and task files go unchecked.
NO_FREEZE_COMMIT = (
    "the preregistration has no freeze commit (no committed prereg/LOCK.json entry), so "
    "the runs' code and task files cannot be checked against it (section 5)"
)


def parse_prereg_fields(text: str) -> tuple[int | None, str | None]:
    """The machine-readable lines of a preregistration: runs per arm and plan digest.

    Both patterns are the ones prereg 0001 section 3 states,
    ``planned_runs_per_config:[ \\t]*(\\d+)`` and ``plan_sha256:[ \\t]*([0-9a-f]{64})``,
    with nothing added: the value follows its name on the same line (spaces or tabs
    between), the digits of ``planned_runs_per_config`` and the first 64 lowercase hex
    digits of ``plan_sha256``. The first match of each pattern counts, even when more
    characters follow it on its line, as the patterns read. A line that does not match
    (for example the draft's ``TO FIX BEFORE FREEZE``) gives None, which
    :func:`run_checks` reports as a confirmatory blocker.
    """
    planned = _PLANNED.search(text)
    digest = _PLAN_SHA.search(text)
    return (int(planned.group(1)) if planned else None, digest.group(1) if digest else None)


@dataclass(frozen=True)
class StudyPlan:
    """The planned runs of ``plan.json``, with the file's path and digests.

    Attributes:
        path: Repository-relative path of ``plan.json``.
        sha256: SHA-256 of the file's bytes (what ``tools/bank_study.py`` records, and
            the digest the preregistration must record).
        runs: The planned runs.
        canonical_sha256: SHA-256 of the content's canonical JSON (sorted keys, compact
            separators, UTF-8), :meth:`receipts.study.plan.Plan.sha256`: reported, not
            accepted as the preregistered digest.
    """

    path: str
    sha256: str
    runs: tuple[Mapping[str, Any], ...]
    canonical_sha256: str


def study_plan(data: Mapping[str, Any], *, path: str, sha256: str) -> StudyPlan:
    """A :class:`StudyPlan` from the content of ``plan.json``.

    Args:
        data: The parsed content of ``plan.json``.
        path: Its repository-relative path.
        sha256: The SHA-256 of its bytes; the canonical digest is computed from ``data``.

    Raises:
        ValueError: There is no runs list, or a planned run lacks run_id, task_id,
            config_id, conditions, or seed.
    """
    runs = data.get("runs")
    if not isinstance(runs, list):
        raise ValueError(f"{path} has no runs list")
    needed = ("run_id", "task_id", "config_id", "conditions", "seed")
    checked: list[Mapping[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, Mapping) or any(name not in run for name in needed):
            raise ValueError(f"{path}: planned run {index} lacks one of {', '.join(needed)}")
        checked.append(dict(run))
    return StudyPlan(
        path=path,
        sha256=sha256,
        runs=tuple(checked),
        canonical_sha256=sha256_text(canonical_json(data)),
    )


# Strict JSON -----------------------------------------------------------------------------


def strict_json(value: Any) -> tuple[Any, list[dict[str, str]]]:
    """A JSON-ready copy of ``value`` without NaN or infinity, and where each one was.

    Mappings (string keys only), lists, tuples, strings, booleans, integers, floats, and
    None are copied (numpy scalars become Python ones). Every non-finite float becomes
    None and is listed as ``{"path": "a.b[2]", "value": "nan" | "inf" | "-inf"}``.

    Raises:
        TypeError: A key is not a string or a value is not JSON data.
    """
    replaced: list[dict[str, str]] = []

    def walk(item: Any, path: str) -> Any:
        if item is None or isinstance(item, str):
            return item
        if isinstance(item, bool | np.bool_):
            return bool(item)
        if isinstance(item, int | np.integer):
            return int(item)
        if isinstance(item, float | np.floating):
            number = float(item)
            if math.isfinite(number):
                return number
            kind = "nan" if math.isnan(number) else ("inf" if number > 0 else "-inf")
            replaced.append({"path": path or "$", "value": kind})
            return None
        if isinstance(item, Mapping):
            out: dict[str, Any] = {}
            for key, sub in item.items():
                if not isinstance(key, str):
                    raise TypeError(f"{path or '$'}: mapping keys must be strings, got {key!r}")
                out[key] = walk(sub, f"{path}.{key}" if path else key)
            return out
        if isinstance(item, list | tuple):
            return [walk(sub, f"{path}[{i}]") for i, sub in enumerate(item)]
        raise TypeError(f"{path or '$'}: {type(item).__name__} is not JSON data")

    return walk(value, ""), replaced


def _exp(value: float) -> float:
    """``exp(value)``, infinite instead of OverflowError (NaN stays NaN)."""
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _listed(ids: Sequence[str], limit: int = 5) -> str:
    """The first ``limit`` ids, comma-separated, with ``...`` when there are more."""
    return ", ".join(ids[:limit]) + (", ..." if len(ids) > limit else "")


# Instrument validity (which claim types count toward Y2) --------------------------------


def instrument_section(
    valid: rescore.ValidTypes, rows_check: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The ``instrument`` section of the E1 artifact.

    Args:
        valid: The valid types of the held-out evaluation
            (:func:`receipts.study.rescore.valid_types`).
        rows_check: How the rows' instrument records compare with the evaluated one
            (:attr:`ProvenanceCheck.instrument`).

    Returns:
        The shared rule and thresholds, the valid types, per-type counts with Wilson 95
        percent intervals for precision and recall, the evaluated instrument (its
        ``commit``, which section 5 fixes the instrument at, paths, and git trees), the
        SHA-256 of the evaluation file, and the rows' check.
    """
    types: dict[str, Any] = {}
    for name, counts in valid.per_type.items():
        precision = wilson_rate(counts.correct, counts.predicted)
        recall = wilson_rate(counts.correct, counts.gold)
        types[name] = {
            **counts.as_dict(),
            "precision_ci_low": precision["ci_low"],
            "precision_ci_high": precision["ci_high"],
            "recall_ci_low": recall["ci_low"],
            "recall_ci_high": recall["ci_high"],
            "counts_toward_y2": counts.valid,
        }
    evaluated = valid.instrument
    section: dict[str, Any] = {
        "rule": rescore.VALID_TYPE_RULE,
        "thresholds": {
            "gold_min": rescore.GOLD_MIN,
            "precision_min": rescore.PRECISION_MIN,
            "recall_min": rescore.RECALL_MIN,
        },
        "valid_types": list(valid.types),
        "types": types,
        "evaluated_commit": evaluated["commit"],
        "evaluated_instrument": {
            "commit": evaluated["commit"],
            "paths": list(evaluated["paths"]),
            "trees": dict(evaluated["trees"]),
        },
        "seeded_eval_sha256": valid.sha256,
        "rows": dict(rows_check or {}),
    }
    if not valid.types:
        section["note"] = (
            "no claim type met the rule, so Y2 is 0 for every run and its tests are not estimable"
        )
    return section


# Rows -----------------------------------------------------------------------------------


def synthetic_flag(rows: Sequence[Row]) -> bool:
    """True when every row is synthetic, False when none is.

    Raises:
        ValueError: There are no rows, a flag is not a boolean, or the rows mix
            synthetic and real runs (pooling them is never allowed).
    """
    if not rows:
        raise ValueError("no runs to analyze")
    flags: set[bool] = set()
    for index, row in enumerate(rows):
        flag = row.get("synthetic")
        if not isinstance(flag, bool):
            raise ValueError(
                f"row {index} ({row.get('run_id')!r}): synthetic must be true or false"
            )
        flags.add(flag)
    if len(flags) > 1:
        raise ValueError("the rows mix synthetic and real runs; refusing to pool them")
    return flags.pop()


_TEXT_FIELDS: tuple[str, ...] = ("run_id", "config_id", "model_family", "task_id")
_BOOL_FIELDS: tuple[str, ...] = (
    "included",
    "completed",
    "false_success",
    "synthetic",
    "instrument_dirty",
    "runtime_agrees",
)
_RUN_CODE_TEXT: tuple[str, ...] = ("git_sha", "code", "snapshot_of")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_instrument(value: object) -> bool:
    """True for an instrument record: commit, paths, trees, dirty, uncommitted."""
    if not isinstance(value, Mapping):
        return False
    trees = value.get("trees")
    return (
        isinstance(value.get("commit"), str)
        and bool(value.get("commit"))
        and _text_list(value.get("paths"))
        and isinstance(trees, Mapping)
        and all(isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in trees.items())
        and isinstance(value.get("dirty"), bool)
        and _text_list(value.get("uncommitted"))
    )


def _is_run_code(value: object) -> bool:
    """True for a run code record: git_sha, code, snapshot_of, uncommitted_src."""
    if not isinstance(value, Mapping) or "uncommitted_src" not in value:
        return False
    texts = all(
        k in value and (value[k] is None or isinstance(value[k], str)) for k in _RUN_CODE_TEXT
    )
    src = value["uncommitted_src"]
    return texts and (src is None or _text_list(src))


def _check_row(row: Row, label: str) -> None:
    """Refuse a row whose scalar or rescoring fields break the row contract."""
    for name in _TEXT_FIELDS:
        if not isinstance(row.get(name), str):
            raise ValueError(f"{label}: {name} must be a str")
    for name in _BOOL_FIELDS:
        if not isinstance(row.get(name), bool):
            raise ValueError(f"{label}: {name} must be a bool")
    if not _is_int(row.get("seed")):
        raise ValueError(f"{label}: seed must be an integer")
    omissions = row.get("omissions")
    if not (isinstance(omissions, int) and not isinstance(omissions, bool) and omissions >= 0):
        raise ValueError(f"{label}: omissions must be a non-negative integer")
    truth = row.get("ground_truth_success", "absent")
    if truth is not None and not isinstance(truth, bool):
        raise ValueError(f"{label}: ground_truth_success must be true, false, or null")
    if row.get("mitigation") != "none":
        raise ValueError(
            f"{label}: mitigation must be 'none' in an E1 row, not {row.get('mitigation')!r}"
        )
    digest = row.get("report_sha256")
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise ValueError(f"{label}: report_sha256 must be 64 lowercase hex digits")
    tree = row.get("task_tree_sha256", 0)
    if tree is not None and not isinstance(tree, str):
        raise ValueError(f"{label}: task_tree_sha256 must be text or null")
    if not _is_instrument(row.get("instrument")):
        raise ValueError(
            f"{label}: instrument must be an instrument record (commit, paths, trees, "
            "dirty, uncommitted)"
        )
    if not _is_run_code(row.get("run_code")):
        raise ValueError(
            f"{label}: run_code must be a mapping of git_sha, code, and snapshot_of (text "
            "or null) and uncommitted_src (a list of paths or null)"
        )


def _conditions(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}: conditions must be a mapping")
    if set(value) != set(MANIPULATIONS):
        raise ValueError(f"{label}: conditions must name exactly {', '.join(MANIPULATIONS)}")
    for factor in MANIPULATIONS:
        if value[factor] not in CONDITION_LEVELS[factor]:
            raise ValueError(f"{label}: {factor}={value[factor]!r} is not a level of {factor}")
    return {factor: str(value[factor]) for factor in MANIPULATIONS}


def _is_evidence(value: object) -> bool:
    """A list of ledger event numbers (non-negative integers, not booleans)."""
    return isinstance(value, list) and all(_is_int(s) and s >= 0 for s in value)


def _claims(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{label}: claims must be a list")
    out: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("claim_id"), str)
            or not isinstance(item.get("claim_type"), str)
            or not isinstance(item.get("text"), str)
            or item.get("verdict") not in VERDICTS
            or not _is_evidence(item.get("evidence"))
        ):
            raise ValueError(
                f"{label}: claim {index} needs claim_id, claim_type, text, a verdict in "
                + ", ".join(sorted(VERDICTS))
                + ", and evidence (a list of ledger event numbers)"
            )
        out.append(
            {
                "claim_id": item["claim_id"],
                "claim_type": item["claim_type"],
                "verdict": item["verdict"],
            }
        )
    ids = [c["claim_id"] for c in out]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{label}: claim ids repeat")
    return out


def analysis_records(rows: Sequence[Row], valid: Iterable[str]) -> list[dict[str, Any]]:
    """One validated analysis record per row, with the outcomes Y1 to Y4.

    Each record has the run's ids, ``family`` (the row's ``model_family``), ``size``
    (:data:`ARM_SIZE`, None for other arms), the five manipulation levels at the top
    level, ``included``, ``completed``, ``synthetic``, ``has_hidden_result``, ``Y1`` to
    ``Y4`` (module docstring; ``Y1`` is None without a hidden-check result), claim counts
    (all types and valid types), and per-type counts
    ``claim_types: {type: {"n": claims, "k": contradicted}}``.

    Raises:
        ValueError: A row breaks the row contract (module docstring, "Rows"), or a run id
            or claim id repeats.
    """
    valid_set = set(valid)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        label = f"row {index} ({row.get('run_id')!r})"
        _check_row(row, label)
        run_id = str(row["run_id"])
        if run_id in seen:
            raise ValueError(f"{label}: run_id repeats")
        seen.add(run_id)
        conditions = _conditions(row.get("conditions"), label)
        omissions = int(row["omissions"])
        claims = _claims(row.get("claims"), label)
        counted = [c for c in claims if c["claim_type"] in valid_set]
        per_type: dict[str, dict[str, int]] = {}
        for item in claims:
            tally = per_type.setdefault(item["claim_type"], {"n": 0, "k": 0})
            tally["n"] += 1
            tally["k"] += int(item["verdict"] == "contradicted")
        judged = row["ground_truth_success"] is not None
        out.append(
            {
                "run_id": run_id,
                ARM: str(row["config_id"]),
                "family": str(row["model_family"]),
                "size": ARM_SIZE.get(str(row["config_id"])),
                TASK: str(row["task_id"]),
                **conditions,
                "included": bool(row["included"]),
                "completed": bool(row["completed"]),
                "synthetic": bool(row["synthetic"]),
                "has_hidden_result": judged,
                "Y1": bool(row["false_success"]) if judged else None,
                "Y2": any(c["verdict"] == "contradicted" for c in counted),
                "Y3": omissions > 0,
                "Y4": not row["completed"],
                "n_claims": len(claims),
                "n_contradicted": sum(c["verdict"] == "contradicted" for c in claims),
                "n_claims_valid": len(counted),
                "n_contradicted_valid": sum(c["verdict"] == "contradicted" for c in counted),
                "claim_types": per_type,
            }
        )
    return out


def analysis_set(records: Sequence[Mapping[str, Any]], outcome: str) -> list[Mapping[str, Any]]:
    """The records ``outcome`` is analyzed over (section 5, :data:`ANALYSIS_SETS`).

    Y1: the included records with a hidden-check result; Y2 and Y3: the included
    records; Y4: every record.
    """
    if outcome == "Y4":
        return list(records)
    included = [r for r in records if r["included"]]
    if outcome == "Y1":
        return [r for r in included if r["Y1"] is not None]
    return included


# Rates (RQ1) ----------------------------------------------------------------------------


def _z(level: float) -> float:
    """The two-sided normal quantile; exactly :data:`Z95` (ship_check's value) at 0.95."""
    return Z95 if level == 0.95 else NormalDist().inv_cdf(0.5 + level / 2.0)


def wilson_rate(
    successes: int, n: int, level: float = 0.95, *, empty_estimate: float | None = None
) -> dict[str, Any]:
    """A rate with its Wilson interval; bounds at ``successes`` 0 or ``n`` set exactly.

    Args:
        successes: Count of successes.
        n: Count of trials.
        level: Interval coverage.
        empty_estimate: The estimate when ``n == 0`` (None: undefined).

    Returns:
        ``estimate``, ``ci_low``, ``ci_high``, ``successes``, ``n``, ``method``, ``level``.
    """
    rate = rate_with_ci(successes, n, _z(level))
    low = 0.0 if successes == 0 else rate.ci_low
    high = 1.0 if successes == n else rate.ci_high
    estimate = rate.estimate if n else empty_estimate
    return {
        "estimate": estimate,
        "ci_low": low,
        "ci_high": high,
        "successes": successes,
        "n": n,
        "method": "wilson",
        "level": level,
    }


def _bootstrap(
    records: Sequence[Mapping[str, Any]],
    statistic: Callable[[Sequence[Mapping[str, Any]]], float],
    settings: E1Settings,
) -> dict[str, Any]:
    result = cluster_bootstrap(
        records, statistic, TASK, n_boot=settings.n_boot, seed=settings.seed, level=settings.level
    )
    return {**result.as_dict(), "cluster": TASK}


def _run_rate(
    records: Sequence[Mapping[str, Any]], outcome: str, settings: E1Settings
) -> dict[str, Any]:
    entry = wilson_rate(sum(1 for r in records if r[outcome]), len(records), settings.level)
    entry["bootstrap"] = _bootstrap(records, mean_statistic(outcome), settings)
    return entry


def _false_success_rate(
    judged: Sequence[Mapping[str, Any]], settings: E1Settings
) -> dict[str, Any]:
    """Y1 over the runs with a hidden-check result; 0 / max(1, n) without one, as g7."""
    if judged:
        return _run_rate(judged, "Y1", settings)
    entry = wilson_rate(0, 0, settings.level, empty_estimate=0.0)
    entry["status"] = "no_hidden_check_result"
    entry["convention"] = "false successes / max(1, runs), as tools/ship_check.py g7 computes it"
    entry["bootstrap"] = None
    return entry


def _claim_rate(
    records: Sequence[Mapping[str, Any]],
    numerator: str,
    denominator: str,
    settings: E1Settings,
    *,
    gate: bool,
) -> dict[str, Any]:
    k = sum(int(r[numerator]) for r in records)
    n = sum(int(r[denominator]) for r in records)
    entry = wilson_rate(k, n, settings.level, empty_estimate=0.0 if gate else None)
    if gate:
        entry["convention"] = "contradicted / max(1, claims), as tools/ship_check.py g7 computes it"
    if n == 0:
        entry["status"] = "no_claims"
        entry["bootstrap"] = None
    else:
        entry["bootstrap"] = _bootstrap(records, ratio_statistic(numerator, denominator), settings)
    return entry


def config_prevalence(
    records: Sequence[Mapping[str, Any]], settings: E1Settings
) -> dict[str, dict[str, Any]]:
    """RQ1 rates per configuration with at least one included run (the ``configs`` section).

    Raises:
        ValueError: A configuration has runs from more than one model family.
    """
    banked: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        banked.setdefault(str(record[ARM]), []).append(record)
    out: dict[str, dict[str, Any]] = {}
    for config in sorted(banked):
        rows = banked[config]
        included = analysis_set(rows, "Y2")
        if not included:
            continue
        judged = analysis_set(rows, "Y1")
        families = sorted({str(r["family"]) for r in rows})
        if len(families) != 1:
            raise ValueError(f"{config} has runs from several model families: {families}")
        out[config] = {
            "n_runs": len(included),
            "n_banked": len(rows),
            "n_hidden_result": len(judged),
            "n_no_hidden_result": len(included) - len(judged),
            "model_family": families[0],
            "size": ARM_SIZE.get(config),
            "false_success_rate": _false_success_rate(judged, settings),
            "contradicted_claim_rate": _claim_rate(
                included, "n_contradicted", "n_claims", settings, gate=True
            ),
            "contradicted_claim_rate_valid_types": _claim_rate(
                included, "n_contradicted_valid", "n_claims_valid", settings, gate=False
            ),
            "any_contradicted_rate": _run_rate(included, "Y2", settings),
            "omission_rate": _run_rate(included, "Y3", settings),
            "non_completion_rate": _run_rate(rows, "Y4", settings),
        }
    return out


def _type_table(
    records: Sequence[Mapping[str, Any]], valid: set[str], settings: E1Settings
) -> dict[str, dict[str, Any]]:
    types = sorted({t for r in records for t in r["claim_types"]})
    table: dict[str, dict[str, Any]] = {}
    for ctype in types:
        per_run = [
            {
                TASK: r[TASK],
                "n": r["claim_types"].get(ctype, {}).get("n", 0),
                "k": r["claim_types"].get(ctype, {}).get("k", 0),
            }
            for r in records
        ]
        entry = wilson_rate(
            sum(x["k"] for x in per_run), sum(x["n"] for x in per_run), settings.level
        )
        entry["bootstrap"] = _bootstrap(per_run, ratio_statistic("k", "n"), settings)
        entry["counts_toward_y2"] = ctype in valid
        table[ctype] = entry
    return table


def claim_type_rates(
    records: Sequence[Mapping[str, Any]], valid: Iterable[str], settings: E1Settings
) -> dict[str, Any]:
    """Per-claim contradiction rate by claim type: pooled over arms and per arm."""
    valid_set = set(valid)
    included = [r for r in records if r["included"]]
    configs = sorted({str(r[ARM]) for r in included})
    return {
        "note": "contradicted claims of a type over claims of that type, among included "
        "runs; the bootstrap resamples tasks; pooled is over every configuration",
        "pooled": _type_table(included, valid_set, settings),
        "by_config": {
            config: _type_table([r for r in included if r[ARM] == config], valid_set, settings)
            for config in configs
        },
    }


# Models and the preregistered tests (RQ2) -----------------------------------------------


def outcome_formula(
    outcome: str, settings: E1Settings, interactions: Sequence[tuple[str, str]] = ()
) -> Formula:
    """The section 7 model of ``outcome``, with optional two-way interactions."""
    return Formula(
        response=outcome,
        factors=(ARM, *MANIPULATIONS),
        interactions=tuple(interactions),
        reference={ARM: settings.reference_arm, **REFERENCE_LEVELS},
        group=TASK,
    )


def _formula_dict(formula: Formula) -> dict[str, Any]:
    return {
        "response": formula.response,
        "factors": list(formula.factors),
        "interactions": [list(pair) for pair in formula.interactions],
        "reference": dict(formula.reference),
        "group": formula.group,
    }


@dataclass(frozen=True)
class OutcomeModel:
    """The model an outcome was analyzed with, after the section 7 fallback rule.

    Attributes:
        outcome: Response field (``Y1`` or ``Y2``).
        formula: The model formula.
        model: ``"glmm"``, ``"logistic"`` (the fallback), or None when nothing was fitted.
        fit: The fit the analysis uses, or None.
        attempted_glmm: The mixed-model fit that was tried, None if it raised.
        fallback: True when the plain logistic fallback is used.
        status: ``"ok"``, ``"fallback"``, ``"no_variation"``, or ``"design_error"``.
        reason: Why the fallback was used or why nothing was fitted.
    """

    outcome: str
    formula: Formula
    model: ModelKind | None
    fit: FitResult | None
    attempted_glmm: FitResult | None
    fallback: bool
    status: Literal["ok", "fallback", "no_variation", "design_error"]
    reason: str = ""

    def summary(self) -> dict[str, Any]:
        """JSON-ready description: model, status, formula, the fit, and the attempt."""
        attempt = self.attempted_glmm
        return {
            "outcome": self.outcome,
            "model": self.model,
            "status": self.status,
            "fallback": self.fallback,
            "reason": self.reason,
            "formula": _formula_dict(self.formula),
            "fit": None if self.fit is None else self.fit.as_dict(),
            "attempted_glmm": None
            if attempt is None
            else {
                "converged": attempt.converged,
                "separation": attempt.separation,
                "separated_terms": list(attempt.separated_terms),
                "warnings": list(attempt.warnings),
                "random_sd": attempt.random_sd,
                "log_likelihood": attempt.log_likelihood,
                "n_agq": attempt.n_agq,
            },
        }


def _try_glmm(design: Design, settings: E1Settings) -> tuple[FitResult | None, str]:
    """The mixed-model fit, or None with the reason it could not be fitted."""
    try:
        fit = fit_glmm(design, n_agq=settings.n_agq, level=settings.level)
    except ValueError as exc:
        return None, f"the mixed model could not be fitted: {exc}"
    if fit.converged and not fit.separation:
        return fit, ""
    return fit, "; ".join(fit.warnings) or "the mixed model did not converge"


def fit_outcome(
    records: Sequence[Mapping[str, Any]], formula: Formula, settings: E1Settings
) -> OutcomeModel:
    """Fit ``formula`` by the section 7 rule: the mixed model, else plain logistic regression.

    ``records`` are the analysis records to model (the outcome's analysis set,
    :func:`analysis_set`).
    """
    events = sum(1 for r in records if r[formula.response])
    if not records or events in (0, len(records)):
        return OutcomeModel(
            formula.response,
            formula,
            None,
            None,
            None,
            False,
            "no_variation",
            f"{events} of {len(records)} runs have {formula.response} = 1",
        )
    try:
        design = build_design(records, formula)
    except ValueError as exc:
        return OutcomeModel(
            formula.response, formula, None, None, None, False, "design_error", str(exc)
        )
    glmm, why = _try_glmm(design, settings)
    if glmm is not None and not why:
        return OutcomeModel(formula.response, formula, "glmm", glmm, glmm, False, "ok")
    logistic = fit_logistic(design, level=settings.level)
    return OutcomeModel(
        formula.response, formula, "logistic", logistic, glmm, True, "fallback", why
    )


def term_estimate(om: OutcomeModel, term: str) -> dict[str, Any]:
    """Wald statistics and odds ratio of one coefficient, or why it is not estimable."""
    base: dict[str, Any] = {"term": term, "model": om.model}
    fit = om.fit
    reason = ""
    if fit is None:
        reason = om.reason
    elif term not in fit.column_names:
        reason = f"{term} is not a column of the model (its level was not observed)"
    elif fit.separation and term in fit.separated_terms:
        reason = "separation: the term lies along the separating direction (no finite estimate)"
    elif not fit.converged and not fit.separation:
        reason = f"the {'mixed' if om.model == 'glmm' else 'plain logistic'} fit did not converge"
    if fit is None or reason:
        return {**base, "status": "not_estimable", "reason": reason, "p_value": None}
    contrast = odds_ratio(fit, term)
    if not (math.isfinite(contrast.se) and math.isfinite(contrast.p_value)):
        reason = "no finite standard error"
        return {**base, "status": "not_estimable", "reason": reason, "p_value": None}
    return {
        **base,
        "status": "ok",
        "log_odds": contrast.estimate,
        "se": contrast.se,
        "z": contrast.z,
        "p_value": contrast.p_value,
        "log_odds_ci_low": contrast.ci_low,
        "log_odds_ci_high": contrast.ci_high,
        "odds_ratio": contrast.odds_ratio,
        "or_ci_low": contrast.or_ci_low,
        "or_ci_high": contrast.or_ci_high,
        "level": contrast.level,
        "fit_separated": fit.separation,
    }


def _lrt_usable(fit: FitResult) -> bool:
    return math.isfinite(fit.log_likelihood) and (fit.converged or fit.separation)


#: How the fallback tests a manipulation (section 7, D42 item 7).
DROP_ONE_METHOD = (
    "likelihood-ratio test of the plain logistic model without the manipulation's column "
    "against the full plain logistic model, chi-square with 1 degree of freedom"
)
#: Section 7: the label of every result that comes from a plain logistic fit.
FALLBACK_LABEL = (
    "plain logistic regression (the section 7 fallback), which treats the runs of a task "
    "as independent"
)


def _fallback_label(logistic: bool) -> dict[str, str]:
    """``{"fallback_label": FALLBACK_LABEL}`` for a plain logistic result, else nothing."""
    return {"fallback_label": FALLBACK_LABEL} if logistic else {}


def drop_one_test(
    records: Sequence[Mapping[str, Any]], om: OutcomeModel, factor: str, settings: E1Settings
) -> dict[str, Any]:
    """The fallback test of one manipulation (section 7): a drop-one likelihood-ratio test.

    ``om`` is the outcome's plain logistic fallback fit of ``records`` (its analysis
    set). The model refitted without ``factor`` (one column, a two-level factor) is
    compared with it, chi-square with 1 degree of freedom. A separated fit enters with the
    log-likelihood where its Newton iterations stop, which approaches its supremum, so
    the test stays defined when a term lies along the separating direction (``status``
    ``ok`` with ``lrt_status`` ``separated``). Without a plain logistic fit, with a fit
    that failed for another reason, or with a model that cannot be refitted, the test is
    not estimable.

    Returns:
        ``status`` (``ok`` or ``not_estimable``) with ``reason``; ``statistic``, ``df``,
        and ``p_value`` (None when not estimable); and, when estimable, ``lrt_status``,
        the convergence and separation of both fits, and ``method``.
    """
    empty: dict[str, Any] = {"statistic": None, "df": None, "p_value": None}

    def not_estimable(reason: str) -> dict[str, Any]:
        return {**empty, "status": "not_estimable", "reason": reason}

    full = om.fit
    term = treatment_column(factor, TREATMENT_LEVELS[factor])
    if full is None:
        return not_estimable(om.reason)
    if om.model != "logistic":
        return not_estimable("the drop-one test applies to the plain logistic fallback only")
    if term not in full.column_names:
        return not_estimable(f"{term} is not a column of the model (its level was not observed)")
    if not _lrt_usable(full):
        return not_estimable("the plain logistic fit did not converge")
    formula = Formula(
        om.outcome,
        tuple(f for f in om.formula.factors if f != factor),
        interactions=tuple(p for p in om.formula.interactions if factor not in p),
        reference={k: v for k, v in om.formula.reference.items() if k != factor},
        group=om.formula.group,
    )
    try:
        restricted = fit_logistic(build_design(records, formula), level=settings.level)
        lrt = likelihood_ratio_test(restricted, full)
    except ValueError as exc:
        return not_estimable(f"the model without {factor} could not be fitted: {exc}")
    if not _lrt_usable(restricted):
        return not_estimable(f"the plain logistic fit without {factor} did not converge")
    if lrt.df != 1:
        return not_estimable(f"the models differ by {lrt.df} parameters, not 1")
    return {
        "status": "ok",
        "reason": "",
        "lrt_status": "ok" if full.converged and restricted.converged else "separated",
        "statistic": lrt.statistic,
        "df": lrt.df,
        "p_value": lrt.p_value,
        "full_converged": full.converged,
        "restricted_converged": restricted.converged,
        "separated": full.separation or restricted.separation,
        "method": DROP_ONE_METHOD,
    }


def _model_bootstrap(
    records: Sequence[Mapping[str, Any]], om: OutcomeModel, settings: E1Settings
) -> dict[str, BootstrapResult]:
    if om.fit is None or om.model is None:
        return {}
    return bootstrap_coefficients(
        records,
        om.formula,
        model=om.model,
        n_agq=settings.n_agq,
        n_boot=settings.n_boot,
        seed=settings.seed,
        level=settings.level,
    )


def _boot_entry(result: BootstrapResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "log_odds_estimate": result.estimate,
        "log_odds_ci_low": result.ci_low,
        "log_odds_ci_high": result.ci_high,
        "or_ci_low": _exp(result.ci_low),
        "or_ci_high": _exp(result.ci_high),
        "n_boot": result.n_boot,
        "n_nonfinite": result.n_nonfinite,
        "n_clusters": result.n_clusters,
        "seed": result.seed,
        "level": result.level,
        "method": "task cluster percentile bootstrap; the model is refitted on every "
        "replicate and replicates that do not converge or are separated are dropped "
        "(n_nonfinite)",
    }


def arm_test(
    analyzed: Sequence[Mapping[str, Any]], om: OutcomeModel, settings: E1Settings
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The arm likelihood-ratio test of one outcome, and any deviations it needed.

    ``analyzed`` is the outcome's analysis set (:func:`analysis_set`), the records
    ``om`` was fitted to.
    """
    base: dict[str, Any] = {"outcome": om.outcome, "alpha": settings.alpha}
    empty = {"statistic": None, "df": None, "p_value": None, "reject": False}
    if om.fit is None or om.model is None:
        return {**base, **empty, "model": None, "status": "not_estimable", "reason": om.reason}, []
    restricted_formula = Formula(om.outcome, MANIPULATIONS, reference=REFERENCE_LEVELS, group=TASK)
    deviations: list[dict[str, Any]] = []
    full_design = build_design(analyzed, om.formula)
    restricted_design = build_design(analyzed, restricted_formula)
    model: ModelKind = om.model
    full: FitResult = om.fit
    restricted: FitResult | None = None
    if model == "glmm":
        attempt, why = _try_glmm(restricted_design, settings)
        if attempt is not None and not why:
            restricted = attempt
        else:
            model = "logistic"
            full = fit_logistic(full_design, level=settings.level)
            deviations.append(
                {
                    "kind": "arm_test_fallback",
                    "outcome": om.outcome,
                    "prereg_section": "7",
                    "detail": f"the mixed model without the arm factor failed ({why}); the arm "
                    f"likelihood-ratio test of {om.outcome} compares plain logistic models",
                }
            )
    if restricted is None:
        restricted = fit_logistic(restricted_design, level=settings.level)
    lrt = likelihood_ratio_test(restricted, full)
    usable = _lrt_usable(full) and _lrt_usable(restricted)
    if full.converged and restricted.converged:
        status = "ok"
    else:
        status = "separated" if usable else "not_converged"
    p_value = lrt.p_value if usable else None
    if lrt.df != ARM_TEST_DF:
        deviations.append(
            {
                "kind": "arm_test_df",
                "outcome": om.outcome,
                "prereg_section": "6",
                "detail": f"the arm factor has {lrt.df + 1} levels, so its test has {lrt.df} "
                f"degrees of freedom (preregistered: {ARM_TEST_DF})",
            }
        )
    return {
        **base,
        "model": model,
        "status": status,
        "statistic": lrt.statistic if usable else None,
        "df": lrt.df,
        "p_value": p_value,
        "reject": p_value is not None and p_value <= settings.alpha,
        "boundary": lrt.boundary,
        "full_converged": full.converged,
        "restricted_converged": restricted.converged,
        "separated": full.separation or restricted.separation,
        **_fallback_label(model == "logistic"),
    }, deviations


def _manipulation_test(
    analyzed: Sequence[Mapping[str, Any]],
    om: OutcomeModel,
    factor: str,
    boots: Mapping[str, BootstrapResult],
    settings: E1Settings,
) -> dict[str, Any]:
    """The preregistered test of one manipulation for one outcome (section 6)."""
    term = treatment_column(factor, TREATMENT_LEVELS[factor])
    estimate = term_estimate(om, term)
    entry: dict[str, Any] = {
        "id": f"{om.outcome}:{factor}",
        "outcome": om.outcome,
        "manipulation": factor,
        "level": TREATMENT_LEVELS[factor],
        "reference_level": REFERENCE_LEVELS[factor],
        **estimate,
    }
    if om.fallback:
        lrt = drop_one_test(analyzed, om, factor, settings)
        entry.update(
            test="likelihood_ratio",
            estimate_status=estimate["status"],
            estimate_reason=estimate.get("reason", ""),
            wald_p_value=estimate["p_value"],
            status=lrt["status"],
            reason=lrt["reason"],
            p_value=lrt["p_value"],
            lrt=lrt,
        )
    else:
        entry["test"] = "wald"
    entry.update(_fallback_label(om.fallback))
    entry["bootstrap"] = _boot_entry(boots.get(term))
    return entry


def preregistered_tests(
    records: Sequence[Mapping[str, Any]], settings: E1Settings
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The section 6 tests from the section 7 model, and the deviations they needed.

    Args:
        records: Analysis records of every banked run (each outcome is modeled over its
            analysis set, :func:`analysis_set`).
        settings: Analysis settings.

    Returns:
        ``(tests, deviations)``: the Holm family of ten manipulation tests, the arm tests,
        the arm odds ratios, and the models; and the fallback deviations.
    """
    deviations: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    models: dict[str, Any] = {}
    arm_tests: dict[str, Any] = {}
    arm_effects: dict[str, list[dict[str, Any]]] = {}
    for outcome in PRIMARY_OUTCOMES:
        analyzed = analysis_set(records, outcome)
        om = fit_outcome(analyzed, outcome_formula(outcome, settings), settings)
        models[outcome] = {
            **om.summary(),
            "analysis_set": ANALYSIS_SETS[outcome],
            "n_analyzed": len(analyzed),
            **_fallback_label(om.fallback),
        }
        if om.fallback:
            deviations.append(
                {
                    "kind": "model_fallback",
                    "outcome": outcome,
                    "prereg_section": "7",
                    "detail": f"the mixed model of {outcome} did not converge or showed "
                    f"separation ({om.reason}); {outcome} is analyzed with plain logistic "
                    "regression, which treats the runs of a task as independent: its "
                    "manipulations are tested by drop-one likelihood-ratio tests, and its "
                    "intervals come from a plain logistic cluster bootstrap",
                }
            )
        boots = _model_bootstrap(analyzed, om, settings)
        for factor in MANIPULATIONS:
            tests.append(_manipulation_test(analyzed, om, factor, boots, settings))
        prefix = f"{ARM}[T."
        names = om.fit.column_names if om.fit is not None else ()
        arm_effects[outcome] = [
            {
                "arm": name[len(prefix) : -1],
                **term_estimate(om, name),
                **_fallback_label(om.fallback),
                "bootstrap": _boot_entry(boots.get(name)),
            }
            for name in names
            if name.startswith(prefix)
        ]
        arm_tests[outcome], found = arm_test(analyzed, om, settings)
        deviations.extend(found)
    in_family = [t["p_value"] if t["status"] == "ok" else 1.0 for t in tests]
    holm = holm_bonferroni(in_family, alpha=settings.alpha)
    for test, p_in, adjusted, reject in zip(
        tests, in_family, holm.adjusted, holm.reject, strict=True
    ):
        test.update(p_value_in_family=p_in, p_holm=adjusted, reject=reject)
    return {
        "family": [t["id"] for t in tests],
        "alpha": settings.alpha,
        "method": "holm-bonferroni",
        "rule": "two-sided Wald test of each manipulation coefficient in the section 7 "
        "mixed model; when an outcome uses the section 7 fallback, the "
        + DROP_ONE_METHOD
        + "; a test that is not estimable enters the family with p = 1",
        "manipulation_tests": tests,
        "arm_tests": arm_tests,
        "arm_effects": arm_effects,
        "models": models,
    }, deviations


# Exploratory interactions ---------------------------------------------------------------


def _exploratory_entries(
    analyzed: Sequence[Mapping[str, Any]],
    formula: Formula,
    terms: Sequence[str],
    settings: E1Settings,
    kind: str,
    interaction: str,
) -> list[dict[str, Any]]:
    om = fit_outcome(analyzed, formula, settings)
    return [
        {
            "outcome": formula.response,
            "kind": kind,
            "interaction": interaction,
            **term_estimate(om, term),
            "fallback": om.fallback,
            **_fallback_label(om.fallback),
            "model_status": om.status,
        }
        for term in terms
    ]


def exploratory_interactions(
    records: Sequence[Mapping[str, Any]], settings: E1Settings
) -> dict[str, Any]:
    """Exploratory two-way interactions for Y1 and Y2 (module docstring), labeled so.

    Each outcome's models are fitted over its analysis set (:func:`analysis_set`).
    """
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for outcome in PRIMARY_OUTCOMES:
        analyzed = analysis_set(records, outcome)
        configs = sorted({str(r[ARM]) for r in analyzed})
        unknown = [c for c in configs if c not in ARM_SIZE]
        ref_family = next((r["family"] for r in analyzed if r[ARM] == settings.reference_arm), None)
        families = sorted({str(r["family"]) for r in analyzed})
        for a, b in combinations(MANIPULATIONS, 2):
            entries += _exploratory_entries(
                analyzed,
                outcome_formula(outcome, settings, ((a, b),)),
                [interaction_column(a, TREATMENT_LEVELS[a], b, TREATMENT_LEVELS[b])],
                settings,
                "manipulation x manipulation",
                f"{a}:{b}",
            )
        if unknown or ref_family is None or settings.reference_arm not in ARM_SIZE:
            skipped.append(
                {
                    "outcome": outcome,
                    "kinds": ["manipulation x family", "manipulation x size"],
                    "reason": f"arm sizes are known only for {', '.join(ARM_SIZE)}; the "
                    f"analyzed arms are {', '.join(configs)} and the reference arm is "
                    f"{settings.reference_arm}",
                }
            )
            continue
        reference = {"family": ref_family, "size": ARM_SIZE[settings.reference_arm]}
        moderators = {
            "family": [f for f in families if f != reference["family"]],
            "size": sorted({ARM_SIZE[c] for c in configs} - {reference["size"]}),
        }
        for moderator, others in moderators.items():
            if not others:
                skipped.append(
                    {
                        "outcome": outcome,
                        "kinds": [f"manipulation x {moderator}"],
                        "reason": f"only one {moderator} level ({reference[moderator]}) "
                        "among the analyzed runs",
                    }
                )
                continue
            for factor in MANIPULATIONS:
                formula = Formula(
                    outcome,
                    ("family", "size", *MANIPULATIONS),
                    interactions=(("family", "size"), (factor, moderator)),
                    reference={**reference, **REFERENCE_LEVELS},
                    group=TASK,
                )
                terms = [
                    interaction_column(factor, TREATMENT_LEVELS[factor], moderator, level)
                    for level in others
                ]
                entries += _exploratory_entries(
                    analyzed, formula, terms, settings, f"manipulation x {moderator}", factor
                )
    return {
        "label": "EXPLORATORY",
        "note": "Not preregistered as tests (prereg 0001 section 7). Each two-way interaction "
        "is added alone to the section 7 model (family and size models replace the arm "
        "factor by family + size + family:size); p-values are unadjusted and support no "
        "confirmatory claim.",
        "interactions": entries,
        "skipped": skipped,
    }


# Rows against the banked runs (section 5) -------------------------------------------------


@dataclass(frozen=True)
class BankedRuns:
    """The banked runs and the banking record the rows must come from (section 5).

    ``tools/analyze.py`` reads them: the ``run.json`` of every banked run under
    ``artifacts/studies/e1/runs/`` and the record ``tools/bank_study.py e1`` writes
    beside the rows (``artifacts/e1/runs.provenance.json``).

    Attributes:
        runs_dir: Repository-relative path of the banked run directories.
        records: Each banked run's ``run.json``, by run id (its directory's name).
        rows_path: Repository-relative path of the rows file that was read.
        rows_sha256: SHA-256 of that file's bytes.
        banking_path: Repository-relative path of the banking record.
        banking: The banking record, or None when there is none (a blocker).
    """

    runs_dir: str
    records: Mapping[str, Mapping[str, Any]]
    rows_path: str
    rows_sha256: str
    banking_path: str
    banking: Mapping[str, Any] | None


@dataclass(frozen=True)
class BankingCheck:
    """How the rows compare with the banked runs (:func:`banking_checks`).

    Attributes:
        section: The ``banking`` section of the artifact.
        blockers: The problems that block a confirmatory artifact.
    """

    section: dict[str, Any]
    blockers: list[str]


#: Confirmatory blocker: the rows were not compared with the banked runs.
BANKED_RUNS_NOT_READ = (
    "the rows were not compared with the banked runs and their banking record, so they "
    "are not shown to be the rows `python tools/bank_study.py e1` wrote for every banked "
    "run (section 5)"
)
#: The ``run.json`` fields a row copies unchanged (``receipts.study.aggregate.run_row``).
_COPIED_FIELDS: tuple[str, ...] = (
    "run_id",
    "config_id",
    "model",
    "task_id",
    "conditions",
    "seed",
    "stop_reason",
    "turns",
)


def _same(left: object, right: object) -> bool:
    """Equal as JSON values, so ``1``, ``1.0``, and ``true`` all differ."""
    try:
        return canonical_json(left) == canonical_json(right)
    except (TypeError, ValueError):
        return False


def row_differences(row: Row, record: Mapping[str, Any]) -> list[str]:
    """The fields in which a row differs from what ``tools/bank_study.py e1`` builds
    from the banked ``run.json`` ``record`` (:func:`receipts.study.aggregate.run_row`).

    Compared: the fields the row copies (``run_id``, ``config_id``, ``model``,
    ``task_id``, ``conditions``, ``seed``, ``stop_reason``, ``turns``; the rescoring
    refuses a run whose stop reason or turns differ from its ledger's ``run_end``),
    ``model_family`` (the record's ``family``), ``synthetic``, ``mitigation``,
    ``report_sha256``, ``included``, and ``completed`` (from the record's report as the
    ledger stores text, a lone surrogate as U+FFFD, since the rescoring takes the report
    from the ledger and requires the record's to be the same), ``run_code``
    (:func:`receipts.study.aggregate.run_code` of the record's provenance), and
    ``task_tree_sha256``. Values compare as JSON values, so ``1``, ``1.0``, and
    ``true`` differ. The claims, verdicts, and outcomes come from the rescoring of the
    ledger, which ``run.json`` does not hold.

    Returns:
        The names of the fields that differ, sorted.
    """
    expected: dict[str, Any] = {name: record.get(name) for name in _COPIED_FIELDS}
    expected["model_family"] = record.get("family")
    expected["synthetic"] = bool(record.get("synthetic", False))
    expected["mitigation"] = record.get("mitigation", "none")
    differ: list[str] = []
    report = record.get("report")
    if isinstance(report, str):
        stored = stored_text(report)
        included = bool(stored.strip())
        expected["included"] = included
        expected["completed"] = record.get("stop_reason") == "finished" and included
        expected["report_sha256"] = sha256_text(stored)
    else:
        differ += ["completed", "included", "report_sha256"]
    provenance = record.get("provenance")
    try:
        expected["run_code"] = aggregate.run_code(provenance)
    except ValueError:
        differ.append("run_code")
    prov: Mapping[str, Any] = provenance if isinstance(provenance, Mapping) else {}
    expected["task_tree_sha256"] = prov.get("task_tree_sha256")
    differ += [name for name, value in expected.items() if not _same(row.get(name), value)]
    return sorted(set(differ))


def banking_checks(rows: Sequence[Row], banked: BankedRuns | None) -> BankingCheck:
    """Check that the rows are the banking of exactly the banked runs (section 5).

    Section 5 computes every outcome from the row ``tools/bank_study.py e1`` writes for
    each banked run. Each of these blocks a confirmatory artifact: the banked runs were
    not read (``banked`` None, :data:`BANKED_RUNS_NOT_READ`); there is no banking
    record, it is another study's, or its ``rows_sha256`` is not the SHA-256 of the rows
    file (the rows were written or changed after the banking); a banked run has no row
    (the plan accounting would count it as not executed); a row has no banked run; or a
    row differs from its banked ``run.json`` (:func:`row_differences`).

    Returns:
        The :class:`BankingCheck`: the ``banking`` section (what was compared, and the
        run ids of each problem) and the blockers.
    """
    if banked is None:
        return BankingCheck({"checked": False}, [BANKED_RUNS_NOT_READ])
    blockers: list[str] = []
    record = banked.banking
    recorded = None if record is None else record.get("rows_sha256")
    if record is None:
        blockers.append(
            f"there is no banking record {banked.banking_path}, so {banked.rows_path} is not "
            "shown to be the file `python tools/bank_study.py e1` wrote (section 5)"
        )
    else:
        if record.get("study") != "e1":
            blockers.append(
                f"the banking record {banked.banking_path} is not E1's "
                f"(study {record.get('study')!r}), so it does not describe {banked.rows_path}"
            )
        if recorded != banked.rows_sha256:
            blockers.append(
                f"{banked.rows_path} is not the file the banking wrote: its SHA-256 is "
                f"{banked.rows_sha256}, but {banked.banking_path} records rows_sha256 "
                f"{recorded!r}, so the rows were written or changed after the banking "
                "(section 5)"
            )
    ids = [str(r.get("run_id")) for r in rows]
    unrowed = sorted(set(banked.records) - set(ids))
    unbanked = sorted(set(ids) - set(banked.records))
    differing: dict[str, list[str]] = {}
    for run_id, row in zip(ids, rows, strict=True):
        banked_record = banked.records.get(run_id)
        found = [] if banked_record is None else row_differences(row, banked_record)
        if found:
            differing[run_id] = found
    if unrowed:
        blockers.append(
            f"{len(unrowed)} banked run(s) under {banked.runs_dir} have no row in "
            f"{banked.rows_path}, so the analysis would count them as never executed; bank "
            "the runs again with `python tools/bank_study.py e1` (section 5): " + _listed(unrowed)
        )
    if unbanked:
        blockers.append(
            f"{len(unbanked)} row(s) of {banked.rows_path} have no banked run under "
            f"{banked.runs_dir}, so their outcomes come from no banked ledger (section 5): "
            + _listed(unbanked)
        )
    if differing:
        named = sorted({name for names in differing.values() for name in names})
        blockers.append(
            f"{len(differing)} row(s) differ from their banked run.json in "
            + ", ".join(named)
            + ", so they are not the banking of those runs (section 5): "
            + _listed(sorted(differing))
        )
    section: dict[str, Any] = {
        "checked": True,
        "runs_dir": banked.runs_dir,
        "banked_runs": len(banked.records),
        "rows": len(rows),
        "rows_path": banked.rows_path,
        "rows_sha256": banked.rows_sha256,
        "banking_record": banked.banking_path,
        "banking_record_found": record is not None,
        "rows_sha256_matches_banking": None if record is None else recorded == banked.rows_sha256,
        "banked_without_row_run_ids": unrowed,
        "rows_without_banked_run_ids": unbanked,
        "rows_differing_from_run_json": {k: differing[k] for k in sorted(differing)},
        "matches": not blockers,
    }
    return BankingCheck(section, blockers)


# Runs against the plan ------------------------------------------------------------------


def failures_by_run(failures: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The banked failure log's entries by run id, in log order, without ``trace``.

    Every entry counts as one failed attempt of its run (the rule
    ``tools/run_study.py`` counts attempts by). Keys other than ``trace`` are kept.

    Raises:
        ValueError: An entry is not an object with a non-empty text ``run_id``, its
            ``attempt`` is not a positive integer, or its ``error``, ``time``, or
            ``started`` is not text.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for index, entry in enumerate(failures):
        if not isinstance(entry, Mapping):
            raise ValueError(f"failure log entry {index} is not an object")
        run_id = entry.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"failure log entry {index} has no run_id")
        attempt = entry.get("attempt")
        if attempt is not None and (not _is_int(attempt) or attempt < 1):
            raise ValueError(
                f"failure log entry {index} ({run_id}): attempt must be a positive integer"
            )
        for key in ("error", "time", "started"):
            if entry.get(key) is not None and not isinstance(entry.get(key), str):
                raise ValueError(f"failure log entry {index} ({run_id}): {key} must be text")
        kept = {k: copy.deepcopy(v) for k, v in entry.items() if k != "trace"}
        out.setdefault(run_id, []).append(kept)
    return out


def _no_hidden_result(rows: Sequence[Row]) -> tuple[list[str], list[dict[str, Any]]]:
    """Included runs without a hidden-check result, and their deviation (D42 item 8)."""
    missing = [
        r for r in rows if r.get("included") is True and r.get("ground_truth_success") is None
    ]
    ids = sorted(str(r["run_id"]) for r in missing)
    if not ids:
        return ids, []
    by_config = Counter(str(r["config_id"]) for r in missing)
    return ids, [
        {
            "kind": "no_hidden_check_result",
            "prereg_section": "5",
            "detail": f"{len(ids)} included run(s) have no hidden-check result "
            "(ground_truth_success null), so they have no Y1 value and Y1 leaves them out "
            "(DECISIONS D42 item 8)",
            "by_config": dict(sorted(by_config.items())),
            "run_ids": ids,
        }
    ]


def plan_accounting(
    rows: Sequence[Row],
    plan: StudyPlan | None,
    planned_per_config: int | None,
    failures: Sequence[Mapping[str, Any]] | None = None,
    banked_runs: Iterable[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Compare banked rows with the plan and the banked failure log (section 10).

    Args:
        rows: The rows of ``artifacts/e1/runs.jsonl``.
        plan: The study plan, or None when there is none (a blocker).
        planned_per_config: The preregistration's ``planned_runs_per_config``. None
            (the preregistration has no such line) is a blocker
            (:data:`MISSING_PLANNED_RUNS`), with or without a plan, because the planned
            runs per arm cannot then be checked.
        failures: The entries of ``artifacts/studies/e1/failures.jsonl``, or None when
            no failure log was banked (then no missing run counts as excluded).
        banked_runs: The run ids banked under ``artifacts/studies/e1/runs/`` (each a
            directory with ``run.json``), or None when they were not read. A planned
            run without a row that is banked there is listed in
            ``banked_without_row_run_ids``, never as excluded or not executed
            (:func:`banking_checks` blocks such rows).

    Returns:
        ``(accounting, deviations, blockers)``: counts per configuration and the run ids
        involved, with the logged errors of each excluded run and of each unbanked run
        attempted fewer than :data:`MAX_ATTEMPTS` times; the deviations (runs without a
        hidden-check result, the shortfall of planned runs without a row, a broken
        retry rule); and the problems that block a confirmatory artifact.

    Raises:
        ValueError: A failure log entry is malformed (:func:`failures_by_run`).
    """
    blockers: list[str] = []
    no_result, deviations = _no_hidden_result(rows)
    logged = failures_by_run(failures) if failures is not None else {}
    entries = None if failures is None else sum(len(v) for v in logged.values())
    pilot = sorted(str(r["run_id"]) for r in rows if str(r.get("task_id", "")).startswith("pilot-"))
    if pilot:
        blockers.append(
            f"{len(pilot)} banked run(s) use pilot tasks, which section 3 keeps out of E1: "
            + _listed(pilot)
        )
    if planned_per_config is None:
        blockers.append(MISSING_PLANNED_RUNS)
    if plan is None:
        blockers.append("no study plan was given, so banked runs cannot be checked against it")
        return (
            {
                "plan": None,
                "no_hidden_result_run_ids": no_result,
                "failure_log_entries": entries,
            },
            deviations,
            blockers,
        )
    planned: dict[str, Mapping[str, Any]] = {}
    repeated: list[str] = []
    for spec in plan.runs:
        run_id = str(spec["run_id"])
        if run_id in planned:
            repeated.append(run_id)
        planned[run_id] = spec
    if repeated:
        blockers.append(f"{plan.path} repeats run ids: " + _listed(sorted(set(repeated))))
    banked = {str(r["run_id"]): r for r in rows}
    unplanned = sorted(set(banked) - set(planned))
    missing = sorted(set(planned) - set(banked))
    on_disk = set() if banked_runs is None else {str(r) for r in banked_runs}
    unrowed = [r for r in missing if r in on_disk]
    unbanked = [r for r in missing if r not in on_disk]
    excluded_ids = [r for r in unbanked if len(logged.get(r, [])) >= MAX_ATTEMPTS]
    not_executed = [r for r in unbanked if len(logged.get(r, [])) < MAX_ATTEMPTS]
    # Section 10's last two groups: attempted but not banked, and never attempted.
    attempted = [r for r in not_executed if logged.get(r)]
    never_attempted = [r for r in not_executed if not logged.get(r)]
    over_cap = sorted(
        r for r in set(banked) | set(unrowed) if len(logged.get(r, [])) >= MAX_ATTEMPTS
    )
    retried = sorted(r for r in banked if 0 < len(logged.get(r, [])) < MAX_ATTEMPTS)
    unplanned_failures = sorted(set(logged) - set(planned))
    mismatched: list[dict[str, Any]] = []
    for run_id in sorted(set(banked) & set(planned)):
        row, spec = banked[run_id], planned[run_id]
        diffs = [name for name in ("task_id", "config_id", "seed") if row.get(name) != spec[name]]
        if dict(row.get("conditions") or {}) != dict(spec["conditions"]):
            diffs.append("conditions")
        if diffs:
            mismatched.append({"run_id": run_id, "fields": diffs})
    if unplanned:
        blockers.append(
            f"{len(unplanned)} banked run(s) are not in the plan: " + _listed(unplanned)
        )
    if mismatched:
        blockers.append(
            f"{len(mismatched)} banked run(s) differ from the plan in task, arm, conditions, "
            "or seed: " + _listed([m["run_id"] for m in mismatched])
        )
    if over_cap:
        blockers.append(
            f"{len(over_cap)} banked run(s) have {MAX_ATTEMPTS} or more logged failed "
            f"attempts, so the retry rule of section 10 was not kept (a run that fails "
            f"{MAX_ATTEMPTS} attempts is excluded and never run again): " + _listed(over_cap)
        )
        deviations.append(
            {
                "kind": "retry_rule",
                "prereg_section": "10",
                "detail": f"{len(over_cap)} run(s) were banked after {MAX_ATTEMPTS} or more "
                "logged failed attempts",
                "run_ids": over_cap,
            }
        )
    if unplanned_failures:
        blockers.append(
            f"the failure log names {len(unplanned_failures)} run(s) that are not in the "
            "plan, so it is not the log of this plan's runs: " + _listed(unplanned_failures)
        )
    work: dict[str, Counter[tuple[str, str, str]]] = {}
    for spec in plan.runs:
        cell = json.dumps(dict(spec["conditions"]), sort_keys=True)
        work.setdefault(str(spec["config_id"]), Counter())[
            (str(spec["task_id"]), cell, str(spec["seed"]))
        ] += 1
    identical = len({frozenset(c.items()) for c in work.values()}) <= 1
    if not identical:
        blockers.append(
            "the plan does not give every arm identical (task, cell, seed) work (section 3)"
        )
    no_result_set = set(no_result)
    configs = sorted(set(work) | {str(r["config_id"]) for r in rows})
    by_config: dict[str, dict[str, int]] = {}
    for config in configs:
        mine = [str(s["run_id"]) for s in plan.runs if str(s["config_id"]) == config]
        done = [r for r in rows if str(r["config_id"]) == config]
        by_config[config] = {
            "planned": len(mine),
            "banked": len(done),
            "included": sum(1 for r in done if r.get("included") is True),
            "no_hidden_result": sum(1 for r in done if str(r["run_id"]) in no_result_set),
            "missing": sum(1 for r in mine if r not in banked),
            "banked_without_row": sum(1 for r in mine if r in unrowed),
            "excluded": sum(1 for r in mine if r in excluded_ids),
            "not_executed": sum(1 for r in mine if r in not_executed),
            "attempted_not_banked": sum(1 for r in mine if r in attempted),
            "never_attempted": sum(1 for r in mine if r in never_attempted),
        }
    if planned_per_config is not None:
        off = [
            f"{c}={n['planned']}"
            for c, n in by_config.items()
            if n["planned"] != planned_per_config
        ]
        if off:
            blockers.append(
                f"the plan's runs per arm differ from planned_runs_per_config = "
                f"{planned_per_config}: " + ", ".join(off)
            )

    def attempts(run_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {
                "run_id": run_id,
                "config_id": str(planned[run_id]["config_id"]),
                "task_id": str(planned[run_id]["task_id"]),
                "attempts": len(logged[run_id]),
                "errors": logged[run_id],
            }
            for run_id in run_ids
        ]

    if missing:
        unlogged = "" if failures is not None else "; no failure log was banked"
        stale = (
            f"{len(unrowed)} banked under the run directories but without a row (the rows "
            "predate them, a confirmatory blocker), "
            if unrowed
            else ""
        )
        shortfall: dict[str, Any] = {
            "kind": "shortfall",
            "prereg_section": "10",
            "detail": f"{len(missing)} of {len(planned)} planned runs have no row: {stale}"
            f"{len(excluded_ids)} excluded after {MAX_ATTEMPTS} failed attempts "
            f"(infrastructure failures in the banked failure log) and "
            f"{len(not_executed)} not executed ({len(attempted)} of them attempted "
            f"and failed fewer than {MAX_ATTEMPTS} times){unlogged}; the runs with rows "
            "are analyzed as planned",
            "missing_by_config": {c: n["missing"] for c, n in by_config.items() if n["missing"]},
            "excluded_by_config": {c: n["excluded"] for c, n in by_config.items() if n["excluded"]},
            "not_executed_by_config": {
                c: n["not_executed"] for c, n in by_config.items() if n["not_executed"]
            },
            "attempted_not_banked_by_config": {
                c: n["attempted_not_banked"]
                for c, n in by_config.items()
                if n["attempted_not_banked"]
            },
            "never_attempted_by_config": {
                c: n["never_attempted"] for c, n in by_config.items() if n["never_attempted"]
            },
        }
        if unrowed:
            shortfall["banked_without_row_by_config"] = {
                c: n["banked_without_row"] for c, n in by_config.items() if n["banked_without_row"]
            }
        deviations.append(shortfall)
    accounting = {
        "plan": plan.path,
        "plan_sha256": plan.sha256,
        "planned": len(planned),
        "banked": len(rows),
        "included": sum(1 for r in rows if r.get("included") is True),
        "missing": len(missing),
        "missing_run_ids": missing,
        "banked_runs_read": banked_runs is not None,
        "banked_without_row_run_ids": unrowed,
        "excluded_run_ids": excluded_ids,
        "not_executed_run_ids": not_executed,
        "attempted_not_banked_run_ids": attempted,
        "never_attempted_run_ids": never_attempted,
        "excluded": attempts(excluded_ids),
        "unbanked_attempts": attempts(attempted),
        "max_attempts": MAX_ATTEMPTS,
        "failure_log_entries": entries,
        "banked_after_failures": retried,
        "no_hidden_result_run_ids": no_result,
        "unplanned_run_ids": unplanned,
        "mismatched": mismatched,
        "identical_work_across_arms": identical,
        "planned_runs_per_config": planned_per_config,
        "by_config": by_config,
    }
    return accounting, deviations, blockers


def run_checks(
    rows: Sequence[Row],
    prereg: PreregInfo,
    plan: StudyPlan | None,
    *,
    failures: Sequence[Mapping[str, Any]] | None = None,
    banked_runs: Iterable[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], bool | None]:
    """Plan accounting plus the plan digest check, shared by E1 and E2.

    ``failures`` and ``banked_runs`` are as in :func:`plan_accounting`.

    Returns:
        ``(accounting, deviations, blockers, plan_matches)``: as :func:`plan_accounting`
        (which blocks a missing plan or ``planned_runs_per_config`` line), with a
        blocker when the preregistration has no ``plan_sha256:`` line
        (:data:`MISSING_PLAN_DIGEST`) or when that line is not the SHA-256 of the plan
        file's bytes (the canonical content digest is not accepted). ``plan_matches`` is
        None when the plan or the line is missing (each of which is then a blocker),
        else whether the line matches.
    """
    accounting, deviations, blockers = plan_accounting(
        rows, plan, prereg.planned_runs_per_config, failures, banked_runs
    )
    plan_matches: bool | None = None
    if prereg.plan_sha256 is None:
        blockers.append(MISSING_PLAN_DIGEST)
    elif plan is not None:
        plan_matches = prereg.plan_sha256 == plan.sha256
        if not plan_matches:
            canonical = ""
            if prereg.plan_sha256 == plan.canonical_sha256:
                canonical = (
                    "; that is its canonical content SHA-256 (Plan.sha256()), which is not "
                    "accepted: section 3 records the SHA-256 of the bytes of the plan file"
                )
            blockers.append(
                f"{plan.path} has SHA-256 {plan.sha256} (of its bytes; canonical content "
                f"SHA-256 {plan.canonical_sha256}), but the preregistration records "
                f"{prereg.plan_sha256}{canonical}"
            )
    return accounting, deviations, blockers, plan_matches


# Instrument and run provenance (D42) ------------------------------------------------------


@dataclass(frozen=True)
class ProvenanceCheck:
    """The instrument and run provenance checks of a set of rows (:func:`provenance_checks`).

    Attributes:
        instrument: How the rows' instrument records compare with the evaluated one: the
            banking ``commits``, ``trees_match_evaluation``, ``mismatched_run_ids``,
            ``dirty_run_ids``, and the run-time verdict disagreements (a diagnostic).
        runs: ``freeze_commit``, ``code`` (counts and run ids by kind of code), and
            ``task_files`` (tasks whose files changed, runs without a record, tasks the
            freeze commit does not hold).
        deviations: The ``run_code`` and ``task_files_changed`` deviations.
        blockers: The problems that block a confirmatory artifact.
    """

    instrument: dict[str, Any]
    runs: dict[str, Any]
    deviations: list[dict[str, Any]]
    blockers: list[str]


#: What a run's code record means for the committed-code rule (section 5).
_CODE_KINDS: dict[str, str] = {
    "other_snapshot": "snapshot of another commit",
    "working_tree": "working tree without uncommitted changes under src/",
}


def _code_kind(code: Mapping[str, Any], freeze: str | None) -> tuple[str, str | None]:
    """The kind of code a run ran and its commit (section 5, Run code and task files).

    ``uncommitted``: an uncommitted change under ``src/``. ``freeze_snapshot``,
    ``other_snapshot``, or ``unchecked_snapshot`` (no freeze commit to compare): a code
    snapshot with ``snapshot_of``. ``working_tree``: the recorded
    ``uncommitted_at_start`` list names nothing under ``src/``. ``unknown``: the
    provenance records neither a snapshot nor that list.
    """
    src = code.get("uncommitted_src")
    if src:
        return "uncommitted", code.get("git_sha")
    if code.get("code") == "snapshot" and isinstance(code.get("snapshot_of"), str):
        commit = str(code["snapshot_of"])
        if freeze is None:
            return "unchecked_snapshot", commit
        return ("freeze_snapshot" if commit == freeze else "other_snapshot"), commit
    if src == []:
        return "working_tree", code.get("git_sha")
    return "unknown", None


def provenance_checks(
    rows: Sequence[Row],
    valid: rescore.ValidTypes,
    evaluation: Mapping[str, Any],
    freeze: FreezeState,
) -> ProvenanceCheck:
    """Check that every row comes from the evaluated instrument, committed code, and the
    committed task files (sections 5 and 11 item 7, DECISIONS D42 items 1 and 3).

    Args:
        rows: Validated rows of ``artifacts/e1/runs.jsonl`` (:func:`analysis_records`).
        valid: The valid types of the held-out evaluation, with its instrument.
        evaluation: The held-out evaluation itself (its ``instrument.dirty`` and
            ``uncommitted`` are checked here).
        freeze: The freeze commit and its task trees.

    Returns:
        The :class:`ProvenanceCheck`; the module docstring lists what blocks and what is a
        deviation.
    """
    blockers: list[str] = []
    deviations: list[dict[str, Any]] = []
    evaluated = rescore.bound_trees(valid.instrument["trees"])
    raw = evaluation.get("instrument")
    record: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    if record.get("dirty") is not False or record.get("uncommitted"):
        blockers.append(
            "the held-out evaluation does not record a clean instrument (instrument.dirty "
            "false and no uncommitted changes), so its git trees need not be the code it "
            "scored"
        )
    untreed = [p for p in rescore.INSTRUMENT_RECORD_PATHS if not isinstance(evaluated.get(p), str)]
    if untreed:
        blockers.append(
            "the held-out evaluation records no git tree for " + ", ".join(untreed) + ", so "
            "the rows' instrument cannot be compared with the evaluated one"
        )
    ids = [str(r["run_id"]) for r in rows]
    mismatched = sorted(
        rid for rid, r in zip(ids, rows, strict=True) if dict(r["instrument"]["trees"]) != evaluated
    )
    dirty = sorted(
        rid
        for rid, r in zip(ids, rows, strict=True)
        if r["instrument_dirty"] or r["instrument"]["dirty"] or r["instrument"]["uncommitted"]
    )
    if mismatched:
        blockers.append(
            f"{len(mismatched)} row(s) were rescored by an instrument whose git trees differ "
            f"from those of the held-out evaluation (instrument.commit "
            f"{valid.instrument['commit'][:12]}), so their outcomes are not the evaluated "
            "instrument's (DECISIONS D42 item 1): " + _listed(mismatched)
        )
    if dirty:
        blockers.append(
            f"{len(dirty)} row(s) were banked from code with uncommitted changes "
            "(instrument_dirty), so they are exploratory (DECISIONS D42 item 1): " + _listed(dirty)
        )
    runtime = sorted(rid for rid, r in zip(ids, rows, strict=True) if not r["runtime_agrees"])
    instrument = {
        "commits": sorted({str(r["instrument"]["commit"]) for r in rows}),
        "trees_match_evaluation": not mismatched,
        "mismatched_run_ids": mismatched,
        "dirty_run_ids": dirty,
        "runtime_disagreements": len(runtime),
        "runtime_disagreement_run_ids": runtime,
        "runtime_note": "rows whose rescored (claim_type, verdict) list differs from the "
        "verdicts run.json banked at run time; a diagnostic, never an outcome",
    }
    fz = freeze.commit
    kinds: dict[str, list[tuple[str, str | None]]] = {}
    for rid, r in zip(ids, rows, strict=True):
        kind, commit = _code_kind(r["run_code"], fz)
        kinds.setdefault(kind, []).append((rid, commit))
    uncommitted = sorted(rid for rid, _ in kinds.get("uncommitted", []))
    unknown = sorted(rid for rid, _ in kinds.get("unknown", []))
    if uncommitted:
        blockers.append(
            f"{len(uncommitted)} run(s) ran with uncommitted changes under src/ "
            "(run_code.uncommitted_src), so they did not run committed code (section 5): "
            + _listed(uncommitted)
        )
    if unknown:
        blockers.append(
            f"{len(unknown)} run(s) do not record committed code (neither a code snapshot "
            "with snapshot_of nor a working tree's uncommitted_at_start list), so their "
            "code cannot be checked (section 5): " + _listed(unknown)
        )
    other = sorted(rid for kind in _CODE_KINDS for rid, _ in kinds.get(kind, []))
    if fz is not None and other:
        by_code = {
            label: dict(sorted(Counter(c or "unknown commit" for _, c in kinds[kind]).items()))
            for kind, label in _CODE_KINDS.items()
            if kinds.get(kind)
        }
        deviations.append(
            {
                "kind": "run_code",
                "prereg_section": "5",
                "detail": f"{len(other)} of {len(rows)} run(s) did not run the code snapshot of "
                f"the freeze commit {fz[:12]} (DECISIONS D42 item 3); they ran the other "
                "committed code listed by kind and commit",
                "by_code": by_code,
                "run_ids": other,
            }
        )
    code: dict[str, Any] = {
        kind: len(kinds.get(kind, []))
        for kind in ("freeze_snapshot", "other_snapshot", "working_tree", "uncommitted", "unknown")
    }
    if kinds.get("unchecked_snapshot"):
        code["unchecked_snapshot"] = len(kinds["unchecked_snapshot"])
    code.update(other_code_run_ids=other, uncommitted_run_ids=uncommitted, unknown_run_ids=unknown)
    task_files: dict[str, Any] = {
        "checked": fz is not None,
        "changed_tasks": {},
        "not_recorded_run_ids": [],
        "missing_at_freeze": [],
        "missing_at_freeze_run_ids": [],
    }
    if fz is None:
        blockers.append(NO_FREEZE_COMMIT)
    else:
        changed: dict[str, list[str]] = {}
        recorded: dict[str, set[str]] = {}
        not_recorded: list[str] = []
        absent: dict[str, list[str]] = {}
        for rid, r in zip(ids, rows, strict=True):
            task, tree = str(r["task_id"]), r["task_tree_sha256"]
            expected = freeze.task_trees.get(task)
            if expected is None:
                absent.setdefault(task, []).append(rid)
            elif tree is None:
                not_recorded.append(rid)
            elif tree != expected:
                changed.setdefault(task, []).append(rid)
                recorded.setdefault(task, set()).add(str(tree))
        changed_runs = sorted(rid for runs in changed.values() for rid in runs)
        if changed_runs:
            blockers.append(
                f"{len(changed_runs)} run(s) used task files that differ from the task files "
                f"at the freeze commit {fz[:12]} (task_tree_sha256; section 5): "
                + _listed(changed_runs)
            )
            deviations.append(
                {
                    "kind": "task_files_changed",
                    "prereg_section": "5",
                    "detail": f"{len(changed)} task(s) differ from their files at the freeze "
                    f"commit {fz[:12]} in {len(changed_runs)} run(s)",
                    "tasks": {
                        task: {
                            "freeze": freeze.task_trees[task],
                            "recorded": sorted(recorded[task]),
                        }
                        for task in sorted(changed)
                    },
                    "run_ids": changed_runs,
                }
            )
        if not_recorded:
            blockers.append(
                f"{len(not_recorded)} run(s) record no task_tree_sha256, so their task files "
                "cannot be checked (section 5): " + _listed(sorted(not_recorded))
            )
        if absent:
            blockers.append(
                f"the freeze commit holds no task directory for {len(absent)} task(s) the "
                "runs used (bench/tasks/<task_id>/): " + _listed(sorted(absent))
            )
        task_files.update(
            changed_tasks={task: sorted(runs) for task, runs in sorted(changed.items())},
            not_recorded_run_ids=sorted(not_recorded),
            missing_at_freeze=sorted(absent),
            missing_at_freeze_run_ids=sorted(rid for runs in absent.values() for rid in runs),
        )
    return ProvenanceCheck(
        instrument=instrument,
        runs={"freeze_commit": fz, "code": code, "task_files": task_files},
        deviations=deviations,
        blockers=blockers,
    )


# The artifacts ----------------------------------------------------------------------------


def confirmatory_decision(
    prereg: PreregInfo, synthetic: bool, blockers: Iterable[str]
) -> tuple[bool, list[str]]:
    """Whether an artifact may say ``confirmatory: true``, and every reason it may not."""
    reasons: list[str] = []
    if not prereg.frozen:
        detail = "; ".join(prereg.problems) or "it is not in prereg/LOCK.json"
        reasons.append(f"{prereg.path} is not frozen ({detail})")
    if synthetic:
        reasons.append("the input rows are synthetic")
    reasons.extend(blockers)
    return not reasons, reasons


def _finish(artifact: dict[str, Any]) -> dict[str, Any]:
    strict, replaced = strict_json(artifact)
    strict["nonfinite_values"] = replaced
    out: dict[str, Any] = strict
    return out


def _data_label(synthetic: bool) -> str:
    if synthetic:
        return "SYNTHETIC test data: not agent runs, not a study result"
    return "agent runs"


def e1_results(
    rows: Sequence[Row],
    seeded: Mapping[str, Any],
    *,
    prereg: PreregInfo,
    plan: StudyPlan | None,
    provenance: Mapping[str, Any],
    seeded_sha256: str | None = None,
    freeze: FreezeState | None = None,
    failures: Sequence[Mapping[str, Any]] | None = None,
    banked: BankedRuns | None = None,
    settings: E1Settings | None = None,
    blockers: Sequence[str] = (),
    deviations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The E1 artifact (``artifacts/e1/results.json``), as strict JSON data.

    Args:
        rows: The rows of ``artifacts/e1/runs.jsonl``.
        seeded: The held-out G5 evaluation (``artifacts/e0/seeded_eval.json``).
        prereg: The preregistration status (from ``tools/analyze.py``).
        plan: The study plan, or None when there is none (a blocker).
        provenance: The artifact's provenance.
        seeded_sha256: The SHA-256 of the evaluation file's bytes, recorded.
        freeze: The freeze commit and its task trees; None means none was found (a
            blocker, :data:`NO_FREEZE_COMMIT`).
        failures: The banked failure log's entries; None when none was banked.
        banked: The banked runs and the banking record the rows must come from
            (:func:`banking_checks`); None means they were not read (a blocker,
            :data:`BANKED_RUNS_NOT_READ`).
        settings: Analysis settings; default the preregistered ones.
        blockers: Further reasons the artifact cannot be confirmatory, listed first.
        deviations: Further deviations to report, listed first.

    Raises:
        ValueError: The rows are empty, malformed, or mix synthetic and real runs; the
            evaluation is not the held-out split or is malformed
            (:func:`receipts.study.rescore.valid_types`); or a failure log entry is
            malformed.
    """
    settings = settings or E1Settings()
    synthetic = synthetic_flag(rows)
    valid = rescore.valid_types(seeded, sha256=seeded_sha256)
    records = analysis_records(rows, valid.types)
    banking = banking_checks(rows, banked)
    runs, plan_deviations, plan_blockers, plan_matches = run_checks(
        rows,
        prereg,
        plan,
        failures=failures,
        banked_runs=None if banked is None else list(banked.records),
    )
    checked = provenance_checks(rows, valid, seeded, freeze or FreezeState(None))
    all_deviations = [dict(d) for d in deviations] + plan_deviations + checked.deviations
    all_blockers = [*blockers, *banking.blockers, *plan_blockers, *checked.blockers]
    differences = settings.differences()
    if differences:
        all_blockers.append(
            "the analysis settings differ from the preregistered ones: " + "; ".join(differences)
        )
        all_deviations.append(
            {"kind": "settings", "prereg_section": "6 and 7", "detail": "; ".join(differences)}
        )
    configs = config_prevalence(records, settings)
    claim_types = claim_type_rates(records, valid.types, settings)
    tests, test_deviations = preregistered_tests(records, settings)
    exploratory = exploratory_interactions(records, settings)
    confirmatory, reasons = confirmatory_decision(prereg, synthetic, all_blockers)
    return _finish(
        {
            "schema": RESULTS_SCHEMA,
            "experiment": "E1",
            "synthetic": synthetic,
            "data_label": _data_label(synthetic),
            "confirmatory": confirmatory,
            "confirmatory_blockers": reasons,
            "prereg": prereg.path,
            "prereg_sha256": prereg.sha256,
            "prereg_frozen": prereg.frozen,
            "plan": plan.path if plan is not None else None,
            "plan_sha256": plan.sha256 if plan is not None else None,
            "plan_canonical_sha256": plan.canonical_sha256 if plan is not None else None,
            "plan_sha256_matches_prereg": plan_matches,
            "settings": {
                **settings.as_dict(),
                "manipulations": list(MANIPULATIONS),
                "reference_levels": {ARM: settings.reference_arm, **REFERENCE_LEVELS},
                "treatment_levels": dict(TREATMENT_LEVELS),
                "holm_family_size": len(PRIMARY_OUTCOMES) * len(MANIPULATIONS),
                "matches_prereg": not differences,
            },
            "outcomes": dict(OUTCOMES),
            "analysis_sets": dict(ANALYSIS_SETS),
            "instrument": instrument_section(valid, checked.instrument),
            "run_provenance": checked.runs,
            "banking": banking.section,
            "runs": runs,
            "configs": configs,
            "claim_types": claim_types,
            "tests": tests,
            "exploratory": exploratory,
            "deviations": all_deviations + test_deviations,
            "provenance": dict(provenance),
        }
    )


# E2 mechanism (RQ3) ---------------------------------------------------------------------


@dataclass(frozen=True)
class RunEvidence:
    """One run's banked ledger, with the SHA-256 of the file read.

    Attributes:
        run_id: The run directory's name.
        ledger: The verified ledger.
        files: The file read (relative to the ``root`` given to the loader, POSIX) and
            its SHA-256.
    """

    run_id: str
    ledger: Ledger
    files: Mapping[str, str]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_run_evidence(run_dir: Path, root: Path | None = None) -> RunEvidence:
    """Load a run's banked ``ledger.jsonl`` with its hash chain verified.

    The run-time ``verification.json`` is not read: E2 takes each verdict's evidence from
    the rescored row (``claims[].evidence``).

    Raises:
        FileNotFoundError: The ledger is missing.
        ValueError: The ledger's chain is broken.
    """
    ledger_path = run_dir / "ledger.jsonl"
    if not ledger_path.is_file():
        raise FileNotFoundError(f"{ledger_path} is missing")
    ledger = Ledger.load(ledger_path)
    name = ledger_path.relative_to(root).as_posix() if root is not None else str(ledger_path)
    return RunEvidence(run_dir.name, ledger, {name: _sha256(ledger_path)})


def contradicted_claims(rows: Sequence[Row]) -> list[tuple[Row, Mapping[str, Any]]]:
    """``(row, claim)`` for every contradicted claim of an included run (the g8 set).

    Raises:
        ValueError: A (run, claim) pair occurs twice.
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[Row, Mapping[str, Any]]] = []
    for row in rows:
        if row.get("included") is not True:
            continue
        for item in row.get("claims", []):
            if item.get("verdict") != "contradicted":
                continue
            key = (str(row.get("run_id")), str(item.get("claim_id")))
            if key in seen:
                raise ValueError(f"claim {key[1]} of run {key[0]} would be classified twice")
            seen.add(key)
            out.append((row, item))
    return out


def classify_contradicted(
    rows: Sequence[Row], load: Callable[[str], RunEvidence]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Classify every contradicted claim from its run's banked ledger (E2).

    The evidence of each claim's verdict is the rescored row's ``claims[].evidence``.

    Args:
        rows: The rows of ``artifacts/e1/runs.jsonl``.
        load: Returns the :class:`RunEvidence` of a run id (called once per run).

    Returns:
        ``(claims, files)``: one entry per contradicted claim with ``run_id``,
        ``claim_id``, ``claim_type``, ``class``, ``evidence`` (the verdict's event
        numbers), ``detail``, the arm, family, task, and conditions; and the SHA-256 of
        every file read.

    Raises:
        ValueError: A ledger belongs to another run, its final report is not the one the
            row was rescored from (``report_sha256``), a claim's evidence is not a list
            of event numbers or names an event the ledger does not have, or a row's
            conditions are malformed.
    """
    cache: dict[str, RunEvidence] = {}
    files: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for row, item in contradicted_claims(rows):
        run_id, claim_id = str(row["run_id"]), str(item["claim_id"])
        if run_id not in cache:
            evidence_of = load(run_id)
            start = evidence_of.ledger.run_start()
            owner = None if start is None else start.data.get("run_id")
            if owner != run_id:
                raise ValueError(f"{run_id}: the banked ledger belongs to run {owner!r}")
            report = evidence_of.ledger.final_report()
            if report is None or sha256_text(report) != row.get("report_sha256"):
                raise ValueError(
                    f"{run_id}: the banked ledger's final report is not the report the row was "
                    "rescored from (report_sha256)"
                )
            cache[run_id] = evidence_of
            files.update(evidence_of.files)
        run = cache[run_id]
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not _is_evidence(evidence):
            raise ValueError(f"{run_id}: claim {claim_id} evidence must be a list of event numbers")
        beyond = [s for s in evidence if s >= len(run.ledger)]
        if beyond:
            raise ValueError(
                f"{run_id}: claim {claim_id} cites event {beyond[0]}, which the banked ledger "
                f"does not have ({len(run.ledger)} events)"
            )
        mechanism = classify(claim_id, evidence, run.ledger)
        out.append(
            {
                "run_id": run_id,
                "claim_id": claim_id,
                "claim_type": str(item.get("claim_type")),
                "class": mechanism.mechanism,
                "evidence": list(mechanism.evidence),
                "detail": mechanism.detail,
                ARM: str(row["config_id"]),
                "model_family": row.get("model_family"),
                TASK: str(row["task_id"]),
                "conditions": _conditions(row.get("conditions"), f"run {run_id}"),
            }
        )
    return out, files


def _mix(claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {name: sum(1 for c in claims if c["class"] == name) for name in CLASSES}
    n = len(claims)
    return {
        "n": n,
        "counts": counts,
        "proportions": {name: (k / n if n else None) for name, k in counts.items()},
    }


def mechanism_mix(claims: Sequence[Mapping[str, Any]], configs: Sequence[str]) -> dict[str, Any]:
    """The mechanism mix overall, per configuration, and per level of each manipulation.

    Every configuration in ``configs`` and every level of every manipulation is listed,
    with ``n`` 0 and proportions None when it has no contradicted claim.
    """
    return {
        "overall": _mix(claims),
        "by_config": {c: _mix([m for m in claims if m[ARM] == c]) for c in configs},
        "by_condition": {
            factor: {
                level: _mix([m for m in claims if m["conditions"][factor] == level])
                for level in CONDITION_LEVELS[factor]
            }
            for factor in MANIPULATIONS
        },
    }


def e2_mechanism(
    rows: Sequence[Row],
    load: Callable[[str], RunEvidence],
    *,
    prereg: PreregInfo,
    plan: StudyPlan | None,
    provenance: Mapping[str, Any],
    seeded: Mapping[str, Any],
    seeded_sha256: str | None = None,
    freeze: FreezeState | None = None,
    failures: Sequence[Mapping[str, Any]] | None = None,
    banked: BankedRuns | None = None,
    blockers: Sequence[str] = (),
    deviations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The E2 artifact (``artifacts/e2/mechanism.json``), as strict JSON data.

    The rows are validated as E1 validates them (:func:`analysis_records`) and checked
    with E1's :func:`banking_checks`, :func:`run_checks`, and :func:`provenance_checks`,
    as :func:`e1_results` does, so E2 is confirmatory only under E1's rule. The SHA-256
    of every ledger read joins ``provenance["inputs"]``.

    Args:
        rows: The rows of ``artifacts/e1/runs.jsonl``.
        load: Returns the :class:`RunEvidence` of a run id.
        prereg: The preregistration status (from ``tools/analyze.py``).
        plan: The study plan, or None when there is none (a blocker).
        provenance: The artifact's provenance.
        seeded: The held-out G5 evaluation, for the instrument check and the valid types
            of the exploratory mix.
        seeded_sha256: The SHA-256 of the evaluation file's bytes, recorded.
        freeze: The freeze commit and its task trees (None: a blocker).
        failures: The banked failure log's entries; None when none was banked.
        banked: The banked runs and the banking record the rows must come from (None:
            a blocker, :data:`BANKED_RUNS_NOT_READ`).
        blockers: Further reasons the artifact cannot be confirmatory, listed first.
        deviations: Further deviations to report, listed first.

    Raises:
        ValueError: As :func:`synthetic_flag`, :func:`analysis_records`,
            :func:`receipts.study.rescore.valid_types`, :func:`plan_accounting`, and
            :func:`classify_contradicted`.
    """
    synthetic = synthetic_flag(rows)
    valid = rescore.valid_types(seeded, sha256=seeded_sha256)
    records = analysis_records(rows, valid.types)
    banking = banking_checks(rows, banked)
    _, plan_deviations, plan_blockers, plan_matches = run_checks(
        rows,
        prereg,
        plan,
        failures=failures,
        banked_runs=None if banked is None else list(banked.records),
    )
    checked = provenance_checks(rows, valid, seeded, freeze or FreezeState(None))
    claims, files = classify_contradicted(rows, load)
    configs = sorted({str(r[ARM]) for r in records if r["included"]})
    confirmatory, reasons = confirmatory_decision(
        prereg, synthetic, [*blockers, *banking.blockers, *plan_blockers, *checked.blockers]
    )
    inputs = {**dict(provenance.get("inputs", {})), **files}
    valid_set = set(valid.types)
    return _finish(
        {
            "schema": MECHANISM_SCHEMA,
            "experiment": "E2",
            "analysis": "preregistered descriptive analysis of the E1 runs (prereg 0001 "
            "sections 1 and 5): no test and no interval",
            "synthetic": synthetic,
            "data_label": _data_label(synthetic),
            "confirmatory": confirmatory,
            "confirmatory_blockers": reasons,
            "prereg": prereg.path,
            "prereg_sha256": prereg.sha256,
            "prereg_frozen": prereg.frozen,
            "plan": plan.path if plan is not None else None,
            "plan_sha256": plan.sha256 if plan is not None else None,
            "plan_canonical_sha256": plan.canonical_sha256 if plan is not None else None,
            "plan_sha256_matches_prereg": plan_matches,
            "verdict_source": "the rescored verdicts of the rows (claims[].verdict and "
            "claims[].evidence) with each run's banked ledger; the run-time "
            "verification.json is not read",
            "instrument": {
                "evaluated_commit": valid.instrument["commit"],
                "valid_types": list(valid.types),
                "seeded_eval_sha256": valid.sha256,
                "rows": checked.instrument,
            },
            "run_provenance": checked.runs,
            "banking": banking.section,
            "classes": list(CLASSES),
            "class_definitions": dict(CLASS_DEFINITIONS),
            "n_contradicted": len(claims),
            "claims": claims,
            "mix": mechanism_mix(claims, configs),
            "exploratory": {
                "label": "EXPLORATORY",
                "note": "The same mix over the contradicted claims of the valid claim types "
                "only (prereg 0001 section 5); not preregistered as a primary description.",
                "valid_types": list(valid.types),
                "mix": mechanism_mix([c for c in claims if c["claim_type"] in valid_set], configs),
            },
            "deviations": [dict(d) for d in deviations] + plan_deviations + checked.deviations,
            "provenance": {**dict(provenance), "inputs": inputs},
        }
    )
