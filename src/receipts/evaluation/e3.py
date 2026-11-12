"""E3 judge validity (RQ4): the analysis code of ``prereg/0003-e3-judges.md``.

``tools/run_judges.py`` reads the inputs, calls the judges, and writes
``artifacts/e3/judges.json`` and ``artifacts/e3/replies.jsonl`` with this module. Each
part follows the section of the preregistration it names; a choice the text leaves open
is fixed in the docstring of the code that makes it.

Units and sample (section 3). The unit is a claim of an E1 run's final report as
re-extracted and re-verified at banking (DECISIONS D42 item 1): the claims and verdicts
of the run's row in ``artifacts/e1/runs.jsonl`` (``e1_rows`` in
:mod:`receipts.study.aggregate`). The run-time claims in ``run.json`` are diagnostics and
are never read here. The sampling frame is the rows that are included (a non-empty final
report) and have at least one claim (:func:`in_frame`). :func:`draw_sample` draws K runs,
K // 4 from each arm: one ``random.Random(seed)``; for each arm in sorted order of
``config_id``, the arm's eligible run ids, sorted, are sampled with
``rng.sample(ids, K // 4)``; an arm with at most K // 4 eligible runs contributes all of
them and draws nothing from the generator, and its shortfall is reported as a deviation.
K and the seed come from the preregistration's machine-readable lines
(:func:`parse_sample_lines`).

Judges (section 4): :data:`JUDGES`. A judge reads only the run's native transcript
(``transcript.json``) and the id and text of each claim of its row, in report order
(:func:`load_items`, :func:`judge_request`); never the ledger, the verification, a
verdict, or the hidden checks. One call per (judge, sampled run) carries every claim of
the run, through an injectable completion function (:data:`Completion`;
``tools/run_judges.py`` passes ``ModelClient.complete``, which caches by content hash).

Scoring (section 5). Ground truth is each claim's verdict in its row; ``contradicted`` is
the positive class. Labels are parsed with
:func:`receipts.evaluation.judges.parse_labels`; a claim without a parsed label is
unlabeled and counts as not flagged; parse failures are counted by kind
(:func:`reply_status`). The valid types come from the held-out G5 evaluation through
:func:`receipts.study.rescore.valid_types`, the one implementation every analysis uses
(at least 10 gold claims, a prediction, precision of at least 0.95, recall of at least
0.90); results for other types are reported with ``valid_type: false``, because their
ledger verdicts are not validated ground truth.

Analysis (section 6, :func:`score_judge`): per claim type TP, FP, FN, TN, and precision
and recall with Wilson 95 percent intervals; the same pooled over the valid types (the
headline estimate) and over every type, each pooled precision and recall also with a
task cluster bootstrap interval (:func:`bootstrap_detection`); calls, parse failures by
kind, unlabeled claims, label counts, tokens, and wall time. Agreement
(:func:`agreement`), beside validity and never instead of it. Exploratory, labeled so
(:func:`exploratory`): scores by E1 arm, on runs of the judge's own model family against
the other family, and recall by the E2 mechanism class of each ledger-contradicted claim.

Exclusions and stopping (section 7). The retry rule: a call that fails (the backend
raises one of :data:`CALL_ERRORS`) stops the run with :class:`JudgeCallError`, and no
artifact is written; ``tools/run_judges.py`` appends it to ``runs/e3/failures.jsonl`` with
its attempt number (:func:`failure_entry`), cached responses are kept, and a rerun
resumes. Attempts are counted per request (its cache key) from that log
(:func:`failure_counts`), so the count holds across restarts. A call with
:data:`MAX_ATTEMPTS` (three) logged failures cannot be served (:func:`unservable_calls`):
it is not made again, and its run is excluded for both judges (neither judge is called
for it), counted, and reported as a deviation; it is not replaced. A refusal by the
client (offline, billing guard) and a server that cannot start stop the run without
counting an attempt. A sampled run whose transcript is missing or malformed stops the
analysis (:func:`load_items`).

The artifact (section 8, :func:`judges_artifact`, schema :data:`SCHEMA`). The fields
other tools read:

- ``sample``: ``sample_runs`` (K), ``seed``, ``per_arm`` (K // 4), ``arms``
  (``{config_id: {eligible, sampled, shortfall}}``, ``sampled`` in draw order),
  ``sampled_run_ids`` (sorted), ``shortfall``, ``preregistered`` (K and the seed are the
  preregistration's lines), ``prereg_sample_runs``, ``prereg_sample_seed``.
- ``runs``: ``rows``, ``frame`` (eligible rows), ``sampled``, ``judged`` (sampled runs
  that are scored), ``excluded`` (run ids, section 7), ``limit``, ``judges`` (the judge
  ids that ran), and ``complete``: no ``--limit``, the judges that ran are exactly those
  of :data:`JUDGES`, the judged runs are the whole sample, and every sampled run was
  judged by both judges apart from the excluded ones (section 8, condition 4). So
  ``sample.sampled_run_ids`` equals the scored runs of ``items[]`` plus
  ``runs.excluded``, and ``calls[]`` has a served call of each judge for every sampled
  run that is not excluded.
- ``exclusions``: per excluded run, its unservable calls with their logged errors.
- ``judges[]``: ``judge_id``, ``per_type`` (``{type: {tp, fp, fn, tn, claims,
  precision, recall, valid_type}}``), ``pooled`` (``valid_types``, the headline, None
  without a held-out evaluation; ``all_types``), counts of calls and labels, ``usage``.
  ``agreement``; ``exploratory``.
- ``items[]``: one per scored claim (run, task, arm, claim, type, ledger verdict, and
  each judge's label). ``calls[]``: one per (judge, sampled run) with ``status``,
  ``served``, and ``cache_key``. ``replies``: the path, SHA-256, and record count (the
  reply records, one per served call) of the replies file.
- ``confirmatory``, ``confirmatory_problems`` (:func:`confirmatory_problems`, also when
  exploratory), ``deviations``, ``provenance``.

The replies file (``artifacts/e3/replies.jsonl``) holds everything the artifact took from
the run that git does not hold elsewhere, so the artifact can be re-scored without a
model call (DECISIONS D65): a first record (:func:`replies_header`) with each judge's
model server provenance and the text of the failure log the run read (which lives under
``runs/``, ignored by git), then one record per served call (:func:`reply_records`) with
the reply text, tokens, wall time, finish reason, and cache hit. ``tools/run_judges.py
--rescore`` reads it back (:class:`BankedReplies`) and serves every judge request from
it by the request's cache key; a request without a banked reply, or a banked reply that
no call uses, stops the re-score.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import re
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from receipts.analysis.rates import cluster_bootstrap_many
from receipts.client.backends import BackendError
from receipts.client.models import GRANITE_8B, LOCAL_MODELS, QWEN_CODER_7B
from receipts.client.wrapper import ModelRequest, ModelResponse
from receipts.evaluation.judges import (
    LABELS,
    DetectionCounts,
    JudgeConfig,
    build_request,
    parse_labels,
    score_detection,
)
from receipts.evaluation.mechanism import CLASSES as MECHANISM_CLASSES
from receipts.ledger.events import sha256_text
from receipts.study.rescore import ValidTypes as ValidTypes
from receipts.study.rescore import bound_trees
from receipts.study.results_e4 import (
    ConfirmatoryRefusedError,
    PreregStatus,
    finite_or_none,
    rate_summary,
    sha256_file,
    strict_json,
)

SCHEMA = "receipts.e3.judges/2"
REPLIES_SCHEMA = "receipts.e3.replies/2"
"""The ``schema`` of the replies file's first record (:func:`replies_header`)."""
PREREG_PATH = "prereg/0003-e3-judges.md"
ROWS = "artifacts/e1/runs.jsonl"
E1_RESULTS = "artifacts/e1/results.json"
SEEDED_EVAL = "artifacts/e0/seeded_eval.json"

E1_ARMS: tuple[str, ...] = ("ma-granite2b", "ma-granite8b", "ma-qwen1.5b", "ma-qwen7b")
"""The four E1 arms (prereg 0001 section 3), sorted; the sample takes K // 4 from each."""

MAX_ATTEMPTS = 3
"""Failed attempts after which a call cannot be served and its run is excluded."""

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261104
LEVEL = 0.95
"""Bootstrap resamples, its seed, and the coverage of every interval (section 6)."""

EXCLUDED = "excluded"
"""The status of a call that was not made because its run is excluded (section 7)."""

CALL_ERRORS: tuple[type[Exception], ...] = (BackendError,)
"""Exceptions of one call that count as a failed attempt of that call (the retry rule)."""

JUDGES: tuple[JudgeConfig, ...] = (
    JudgeConfig(judge_id="qwen7b-transcript", backend="local", model=QWEN_CODER_7B.name),
    JudgeConfig(judge_id="granite8b-transcript", backend="local", model=GRANITE_8B.name),
)
"""The preregistered judges (section 4): the larger model of each family, transcript only."""

Completion = Callable[[ModelRequest], ModelResponse]
"""Makes one model call; production passes ``ModelClient.complete``, tests a fake judge."""

CHARS_PER_TOKEN = 4.0
"""Dry-run token estimate: characters per token (an approximation, never a measurement)."""

CONTEXT_TOKENS = QWEN_CODER_7B.n_ctx
"""Tokens of context each served slot has (``LocalModel.n_ctx``)."""

PRECISION_UNDEFINED = "undefined: the judge flagged no claim of this type"
RECALL_UNDEFINED = "undefined: the ledger contradicts no claim of this type"
POOLED_PRECISION_UNDEFINED = "undefined: the judge flagged no claim of these types"
POOLED_RECALL_UNDEFINED = "undefined: the ledger contradicts no claim of these types"
BOOTSTRAP_METHOD = "task cluster percentile bootstrap"

GROUND_TRUTH = (
    "the verdict of each claim in its row of artifacts/e1/runs.jsonl, from re-verification "
    "at banking with the evaluated instrument (DECISIONS D42 item 1); contradicted is the "
    "positive class; the run-time claims in run.json are diagnostics and are not used"
)
VALID_TYPE_NOTE = (
    "per_type entries with valid_type false are reported, but the ledger verdicts of those "
    "types are not validated ground truth (prereg 0003 section 5); valid_type null means "
    "no held-out evaluation was read"
)
AGREEMENT_NOTE = (
    "Agreement between judges measures reliability, not validity. Validity is each judge's "
    "precision and recall against the ledger (judges[].per_type and judges[].pooled), "
    "reported beside this and never instead of it."
)
EXPLORATORY_NOTE = (
    "EXPLORATORY (prereg 0003 section 6): not preregistered as estimates; Wilson intervals "
    "only, no bootstrap"
)

_SAMPLE_RUNS = re.compile(r"sample_runs:[ \t]*(\d+)")
_SAMPLE_SEED = re.compile(r"sample_seed:[ \t]*(\d+)")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def describe_config(config: JudgeConfig) -> dict[str, Any]:
    """JSON form of a judge configuration, with the pinned model file when it is local."""
    pin = LOCAL_MODELS.get(config.model) if config.backend == "local" else None
    return {
        "judge_id": config.judge_id,
        "backend": config.backend,
        "model": config.model,
        "model_pin": (
            {
                "family": pin.family,
                "file": pin.path.name,
                "sha256": pin.sha256,
                "source": pin.source,
            }
            if pin is not None
            else None
        ),
        "system_prompt": config.system_prompt,
        "system_prompt_sha256": sha256_text(config.system_prompt),
        "max_transcript_chars": config.max_transcript_chars,
        "params": dict(config.params),
        "reads": "the run's native transcript and the id and text of each claim of its row "
        "(re-extracted from the final report at banking); never the ledger",
        "calls": "one call per sampled run, carrying every claim of that run",
    }


def parse_sample_lines(text: str) -> tuple[int | None, int | None]:
    """``sample_runs`` (K) and ``sample_seed`` from the preregistration's lines (section 3).

    The patterns are ``sample_runs:[ \\t]*(\\d+)`` and ``sample_seed:[ \\t]*(\\d+)``: the
    value is on the same line as its name, and the first match of each pattern counts. A
    placeholder such as ``TO FIX BEFORE FREEZE`` does not match, so it reads as None.
    """
    runs = _SAMPLE_RUNS.search(text)
    seed = _SAMPLE_SEED.search(text)
    return (int(runs.group(1)) if runs else None, int(seed.group(1)) if seed else None)


# Rows and the sampling frame (section 3) --------------------------------------------------


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _check_claims(claims: object, where: str) -> None:
    if not isinstance(claims, list):
        raise ValueError(f"{where}: claims must be a list")
    ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            raise ValueError(f"{where}: claims[{index}] is not an object")
        cid = claim.get("claim_id")
        if not isinstance(cid, str) or not cid:
            raise ValueError(f"{where}: claims[{index}] has no claim_id")
        if cid in ids:
            raise ValueError(f"{where}: claim id {cid} repeats")
        ids.add(cid)
        if not _is_text(claim.get("claim_type")):
            raise ValueError(f"{where}: claim {cid} has no claim_type")
        if not isinstance(claim.get("text"), str):
            raise ValueError(f"{where}: claim {cid} text must be a string")
        if claim.get("verdict") not in LABELS:
            raise ValueError(
                f"{where}: claim {cid} has verdict {claim.get('verdict')!r}, not supported, "
                "contradicted, or unverifiable"
            )


def check_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    """Refuse rows of ``artifacts/e1/runs.jsonl`` that E3 cannot read as the row contract says.

    Every field E3 reads must be present and well typed: ``run_id`` (one safe path
    component, unique), ``config_id``, ``task_id``, ``model_family`` (non-empty strings),
    ``included``, ``synthetic``, ``instrument_dirty`` (booleans), ``instrument`` (an
    object with ``trees``), and ``claims`` (objects with a unique ``claim_id``, a
    ``claim_type``, a ``text``, and a ``verdict`` that is supported, contradicted, or
    unverifiable).

    Raises:
        ValueError: A row breaks one of these rules.
    """
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        where = f"{ROWS} row {number}"
        if not isinstance(row, Mapping):
            raise ValueError(f"{where} is not an object")
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not _SAFE_ID.match(run_id) or ".." in run_id:
            raise ValueError(f"{where}: run_id {run_id!r} is not one safe path component")
        if run_id in seen:
            raise ValueError(f"{ROWS}: run id {run_id} repeats")
        seen.add(run_id)
        where = f"{where} (run {run_id})"
        for name in ("config_id", "task_id", "model_family"):
            if not _is_text(row.get(name)):
                raise ValueError(f"{where}: {name} must be a non-empty string")
        for name in ("included", "synthetic", "instrument_dirty"):
            if not isinstance(row.get(name), bool):
                raise ValueError(f"{where}: {name} must be true or false")
        instrument = row.get("instrument")
        if not isinstance(instrument, Mapping) or not isinstance(instrument.get("trees"), Mapping):
            raise ValueError(f"{where}: instrument must be an object with trees")
        _check_claims(row.get("claims"), where)


def in_frame(row: Mapping[str, Any]) -> bool:
    """Whether a row is in the sampling frame: included, with at least one claim."""
    claims = row.get("claims")
    return row.get("included") is True and isinstance(claims, list) and len(claims) > 0


@dataclass(frozen=True)
class RowClaim:
    """One claim of an E1 row: what the judge is shown (id, text) and its ground truth.

    Attributes:
        claim_id: Its id within the report (``c0``, ``c1``, ...).
        claim_type: Its claim type.
        text: Its text, verbatim from the report.
        verdict: The ledger verdict of re-verification at banking (never shown).
    """

    claim_id: str
    claim_type: str
    text: str
    verdict: str


def row_claims(row: Mapping[str, Any]) -> tuple[RowClaim, ...]:
    """The claims of a row checked by :func:`check_rows`, in report order."""
    return tuple(
        RowClaim(str(c["claim_id"]), str(c["claim_type"]), str(c["text"]), str(c["verdict"]))
        for c in row["claims"]
    )


@dataclass(frozen=True)
class ArmSample:
    """The sample of one arm.

    Attributes:
        config_id: The arm.
        eligible: Its run ids in the sampling frame, sorted.
        sampled: The run ids drawn, in draw order (all of ``eligible`` when it has at most
            K // 4 runs).
        shortfall: K // 4 minus the runs drawn (0 when the arm has enough runs).
    """

    config_id: str
    eligible: tuple[str, ...]
    sampled: tuple[str, ...]
    shortfall: int

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "eligible": list(self.eligible),
            "sampled": list(self.sampled),
            "shortfall": self.shortfall,
        }


SAMPLE_RULE = (
    "one random.Random(seed); for each arm in sorted order of config_id, the arm's eligible "
    "run ids (included, at least one claim), sorted, are sampled with rng.sample(ids, K // 4); "
    "an arm with at most K // 4 eligible runs contributes all of them and draws nothing"
)


@dataclass(frozen=True)
class Sample:
    """The E3 sample of section 3 (:func:`draw_sample`).

    Attributes:
        sample_runs: K.
        seed: The generator's seed.
        arms: One :class:`ArmSample` per arm, in sorted order of ``config_id``: every E1
            arm, and any other arm the rows have.
    """

    sample_runs: int
    seed: int
    arms: tuple[ArmSample, ...]

    @property
    def per_arm(self) -> int:
        """K // 4."""
        return self.sample_runs // len(E1_ARMS)

    @property
    def run_ids(self) -> tuple[str, ...]:
        """Every sampled run id, sorted."""
        return tuple(sorted(run_id for arm in self.arms for run_id in arm.sampled))

    @property
    def shortfall(self) -> int:
        """The runs the arms lack in all."""
        return sum(arm.shortfall for arm in self.arms)

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "sample_runs": self.sample_runs,
            "seed": self.seed,
            "per_arm": self.per_arm,
            "rule": SAMPLE_RULE,
            "arms": {arm.config_id: arm.as_dict() for arm in self.arms},
            "sampled_run_ids": list(self.run_ids),
            "shortfall": self.shortfall,
        }


def draw_sample(rows: Sequence[Mapping[str, Any]], sample_runs: int, seed: int) -> Sample:
    """Draw the sample of section 3 from the rows of ``artifacts/e1/runs.jsonl``.

    One ``random.Random(seed)`` serves every arm. The arms are the four of
    :data:`E1_ARMS` and any other ``config_id`` the rows have, in sorted order (Python's
    string order); the run ids of an arm are sorted before sampling, so neither the row
    order nor the file order matters. An arm with no row is listed with no eligible run,
    and it draws nothing, like every arm with at most K // 4 eligible runs.

    Raises:
        ValueError: K is not a positive multiple of 4, or :func:`check_rows` refuses a row.
    """
    arms_n = len(E1_ARMS)
    if isinstance(sample_runs, bool) or sample_runs < arms_n or sample_runs % arms_n:
        raise ValueError(
            f"the sample size K = {sample_runs} is not a positive multiple of {arms_n}"
        )
    check_rows(rows)
    per_arm = sample_runs // arms_n
    eligible: dict[str, list[str]] = {arm: [] for arm in E1_ARMS}
    for row in rows:
        ids = eligible.setdefault(str(row["config_id"]), [])
        if in_frame(row):
            ids.append(str(row["run_id"]))
    rng = random.Random(seed)
    arms: list[ArmSample] = []
    for arm in sorted(eligible):
        ids = sorted(eligible[arm])
        sampled = ids if len(ids) <= per_arm else rng.sample(ids, per_arm)
        arms.append(ArmSample(arm, tuple(ids), tuple(sampled), per_arm - len(sampled)))
    return Sample(sample_runs, seed, tuple(arms))


# Items (section 4) ----------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeItem:
    """One sampled E1 run as a judge sees it, plus the ground truth it is scored on.

    Attributes:
        run_id: The E1 run.
        task_id: Its task (the bootstrap cluster).
        config_id: Its arm.
        model_family: Its model's family (for the exploratory own-family split).
        synthetic: The ``synthetic`` flag of its row.
        transcript: Native transcript messages (``role`` and ``content``).
        claims: The claims of its row, in report order.
        sources: SHA-256 of each file read for this run, by path relative to the root.
    """

    run_id: str
    task_id: str
    config_id: str
    model_family: str
    synthetic: bool
    transcript: tuple[Mapping[str, str], ...]
    claims: tuple[RowClaim, ...]
    sources: Mapping[str, str]

    @property
    def truth(self) -> dict[str, str]:
        """Ledger verdict per claim id (never shown to a judge)."""
        return {c.claim_id: c.verdict for c in self.claims}

    @property
    def claim_types(self) -> dict[str, str]:
        """Claim type per claim id."""
        return {c.claim_id: c.claim_type for c in self.claims}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _transcript(path: Path, run_id: str) -> tuple[dict[str, str], ...]:
    """The messages of a run's ``transcript.json``; ValueError when it cannot be read."""
    if not path.is_file():
        raise ValueError(
            f"{run_id}: transcript.json is missing ({path}); a sampled run is never dropped"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{run_id}: transcript.json is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{run_id}: transcript.json is not a JSON object")
    messages = data.get("messages")
    if not isinstance(messages, list) or not all(
        isinstance(m, Mapping)
        and isinstance(m.get("role"), str)
        and isinstance(m.get("content"), str)
        for m in messages
    ):
        raise ValueError(
            f"{run_id}: transcript.json messages must be a list of objects with a text role "
            "and content"
        )
    return tuple({"role": m["role"], "content": m["content"]} for m in messages)


def load_items(
    rows: Sequence[Mapping[str, Any]], runs_dir: Path, root: Path, run_ids: Iterable[str]
) -> list[JudgeItem]:
    """One item per run id, sorted by run id: its row's claims and its native transcript.

    Only ``<runs_dir>/<run_id>/transcript.json`` is opened, never the ledger, the
    verification, or ``run.json``: the claims and their ground truth come from the row,
    so the run-time claims are not compared with them (section 7).

    Raises:
        ValueError: :func:`check_rows` refuses a row; a run id has no row or is not in the
            sampling frame; a transcript is missing or malformed.
    """
    check_rows(rows)
    by_id = {str(row["run_id"]): row for row in rows}
    items: list[JudgeItem] = []
    for run_id in sorted(set(run_ids)):
        row = by_id.get(run_id)
        if row is None:
            raise ValueError(f"{run_id}: no row in {ROWS}")
        if not in_frame(row):
            raise ValueError(
                f"{run_id} is not in the sampling frame (an included run with at least one claim)"
            )
        path = runs_dir / run_id / "transcript.json"
        items.append(
            JudgeItem(
                run_id=run_id,
                task_id=str(row["task_id"]),
                config_id=str(row["config_id"]),
                model_family=str(row["model_family"]),
                synthetic=row.get("synthetic") is True,
                transcript=_transcript(path, run_id),
                claims=row_claims(row),
                sources={_rel(path, root): sha256_file(path)},
            )
        )
    return items


def judge_request(config: JudgeConfig, item: JudgeItem) -> ModelRequest:
    """The judge's request for one run (:func:`receipts.evaluation.judges.build_request`).

    The ``purpose`` label names the judge and the run; it never changes the cache key.
    """
    return build_request(
        config, item.transcript, item.claims, purpose=f"e3:judge {config.judge_id} {item.run_id}"
    )


def reply_status(text: str) -> str:
    """``ok``, or which step of :func:`judges.parse_labels` failed for this reply.

    Returns ``no_json_object``, ``invalid_json``, or ``no_labels_list`` (the reply's
    first ``{`` to last ``}`` span is not an object with a ``labels`` list).
    """
    match = _JSON_OBJECT.search(text)
    if match is None:
        return "no_json_object"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return "invalid_json"
    if not isinstance(data, dict) or not isinstance(data.get("labels"), list):
        return "no_labels_list"
    return "ok"


# Calls (sections 4 and 7) ------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeCall:
    """One judge call: the reply, its parsed labels, and what it cost.

    ``served`` is False for a call not made because its run is excluded (status
    :data:`EXCLUDED`, no labels, no text).
    """

    run_id: str
    status: str
    labels: Mapping[str, str]
    cache_key: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    wall_s: float
    finish_reason: str
    text: str = ""
    served: bool = True


@dataclass(frozen=True)
class JudgeRun:
    """Every call of one judge configuration over the items.

    ``synthetic`` marks a fake judge (tests); the artifact is then labeled synthetic.
    """

    config: JudgeConfig
    calls: tuple[JudgeCall, ...]
    synthetic: bool = False


class JudgeCallError(RuntimeError):
    """A judge call failed (the retry rule of section 7): the run stops without an artifact.

    Attributes:
        judge_id: The judge.
        run_id: The run it was asked about.
        cache_key: The request's cache key (attempts are counted per request).
        error: ``"<exception type>: <message>"`` of the backend's exception.
    """

    def __init__(self, judge_id: str, run_id: str, cache_key: str, error: str) -> None:
        super().__init__(f"judge {judge_id} could not judge run {run_id}: {error}")
        self.judge_id = judge_id
        self.run_id = run_id
        self.cache_key = cache_key
        self.error = error


def run_judge(
    config: JudgeConfig,
    items: Sequence[JudgeItem],
    complete: Completion,
    *,
    synthetic: bool = False,
    skip: Collection[str] = (),
) -> JudgeRun:
    """Ask one judge about every item that has claims, one call per item.

    Args:
        config: The judge.
        items: The runs, in the order the calls are made.
        complete: Makes one call.
        synthetic: The judge is a fake (tests).
        skip: Run ids excluded under section 7: no call is made, and the run gets a call
            entry with status :data:`EXCLUDED`.

    Raises:
        JudgeCallError: ``complete`` raised one of :data:`CALL_ERRORS`; nothing after it
            is called. Other exceptions (a client refusal) propagate unchanged.
    """
    calls: list[JudgeCall] = []
    for item in items:
        if not item.claims:
            continue
        request = judge_request(config, item)
        key = request.cache_key()
        if item.run_id in skip:
            calls.append(
                JudgeCall(item.run_id, EXCLUDED, {}, key, False, 0, 0, 0.0, "", served=False)
            )
            continue
        try:
            response = complete(request)
        except CALL_ERRORS as exc:
            raise JudgeCallError(
                config.judge_id, item.run_id, key, f"{type(exc).__name__}: {exc}"
            ) from exc
        calls.append(
            JudgeCall(
                run_id=item.run_id,
                status=reply_status(response.text),
                labels=parse_labels(response.text, (c.claim_id for c in item.claims)),
                cache_key=key,
                cache_hit=response.cache_hit,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                wall_s=response.wall_s,
                finish_reason=response.finish_reason,
                text=response.text,
            )
        )
    return JudgeRun(config, tuple(calls), synthetic)


def failure_entry(error: JudgeCallError, attempt: int, time: str) -> dict[str, Any]:
    """The line ``runs/e3/failures.jsonl`` gets for one failed call."""
    return {
        "judge_id": error.judge_id,
        "run_id": error.run_id,
        "cache_key": error.cache_key,
        "attempt": attempt,
        "time": time,
        "error": error.error,
    }


def _failure_key(entry: object, index: int) -> str:
    if not isinstance(entry, Mapping):
        raise ValueError(f"failure log entry {index} is not an object")
    key = entry.get("cache_key")
    if not isinstance(key, str) or not _SHA256.match(key):
        raise ValueError(
            f"failure log entry {index} has no cache_key (64 lowercase hex digits), so the "
            "attempts of its call cannot be counted"
        )
    return key


def failure_counts(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Logged failed attempts per request cache key; every entry counts as one attempt.

    Raises:
        ValueError: An entry is not an object with a ``cache_key``.
    """
    counts: dict[str, int] = {}
    for index, entry in enumerate(entries):
        key = _failure_key(entry, index)
        counts[key] = counts.get(key, 0) + 1
    return counts


def unservable_calls(
    configs: Sequence[JudgeConfig],
    items: Sequence[JudgeItem],
    entries: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, list[dict[str, Any]]]:
    """The calls that cannot be served, by run id: their runs are excluded (section 7).

    A call cannot be served when its request (cache key) has ``max_attempts`` logged
    failures. Each entry lists the judge, the cache key, the attempts, and the logged
    errors in log order. ``tools/run_judges.py`` passes every judge of :data:`JUDGES`,
    so a run excluded for one judge is excluded for both.

    Raises:
        ValueError: :func:`failure_counts` refuses an entry.
    """
    counts = failure_counts(entries)
    out: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if not item.claims:
            continue
        for config in configs:
            key = judge_request(config, item).cache_key()
            if counts.get(key, 0) < max_attempts:
                continue
            errors = [
                {"attempt": e.get("attempt"), "time": e.get("time"), "error": e.get("error")}
                for e in entries
                if e.get("cache_key") == key
            ]
            out.setdefault(item.run_id, []).append(
                {
                    "judge_id": config.judge_id,
                    "cache_key": key,
                    "attempts": counts[key],
                    "errors": errors,
                }
            )
    return out


# Scoring (sections 5 and 6) ----------------------------------------------------------------


def _labels(run: JudgeRun) -> dict[tuple[str, str], str]:
    return {(call.run_id, cid): label for call in run.calls for cid, label in call.labels.items()}


def _metric(successes: int, n: int, undefined: str) -> dict[str, Any]:
    summary = rate_summary(successes, n, level=LEVEL)
    if n == 0:
        summary["status"] = undefined
    return summary


def _counts(counts: DetectionCounts, precision: str, recall: str) -> dict[str, Any]:
    tp, fp, fn, tn = counts.tp, counts.fp, counts.fn, counts.tn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "claims": tp + fp + fn + tn,
        "precision": _metric(tp, tp + fp, precision),
        "recall": _metric(tp, tp + fn, recall),
    }


def detection_records(
    run: JudgeRun, items: Sequence[JudgeItem], types: Collection[str] | None = None
) -> list[dict[str, Any]]:
    """One record per claim (of ``types``, or every type): its task, truth, and flag.

    Records follow the items sorted by run id, and each run's claims in report order, so
    the bootstrap numbers tasks in their order of first appearance there.
    """
    labels = _labels(run)
    return [
        {
            "task_id": item.task_id,
            "claim_type": claim.claim_type,
            "contradicted": claim.verdict == "contradicted",
            "flagged": labels.get((item.run_id, claim.claim_id)) == "contradicted",
        }
        for item in sorted(items, key=lambda i: i.run_id)
        for claim in item.claims
        if types is None or claim.claim_type in types
    ]


def _tally(records: Sequence[Mapping[str, Any]]) -> DetectionCounts:
    counts = DetectionCounts()
    for record in records:
        if record["contradicted"]:
            if record["flagged"]:
                counts.tp += 1
            else:
                counts.fn += 1
        elif record["flagged"]:
            counts.fp += 1
        else:
            counts.tn += 1
    return counts


def _precision_recall(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Pooled precision and recall of the records; NaN where a denominator is 0."""
    counts = _tally(records)
    flagged, contradicted = counts.tp + counts.fp, counts.tp + counts.fn
    return {
        "precision": counts.tp / flagged if flagged else math.nan,
        "recall": counts.tp / contradicted if contradicted else math.nan,
    }


def bootstrap_detection(
    records: Sequence[Mapping[str, Any]],
    *,
    n_boot: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = LEVEL,
) -> dict[str, dict[str, Any]]:
    """Task cluster bootstrap intervals of the pooled precision and recall (section 6).

    Percentile intervals from ``n_boot`` resamples of tasks with replacement
    (:func:`receipts.analysis.rates.cluster_bootstrap_many`, its resampling scheme; both
    statistics share each replicate). A replicate whose denominator is 0 is dropped and
    counted in ``n_dropped``. The estimate is None, with a status that says why, when the
    statistic is undefined on the records themselves.
    """
    base: dict[str, Any] = {
        "n_boot": n_boot,
        "seed": seed,
        "level": level,
        "resamples": "tasks",
        "method": BOOTSTRAP_METHOD,
    }
    names = ("precision", "recall")
    if not records:
        empty = {"estimate": None, "ci_low": None, "ci_high": None, "n_clusters": 0, "n_dropped": 0}
        return {name: {**base, **empty, "status": "no claims"} for name in names}
    results = cluster_bootstrap_many(
        records, _precision_recall, "task_id", n_boot=n_boot, seed=seed, level=level, names=names
    )
    undefined = {"precision": POOLED_PRECISION_UNDEFINED, "recall": POOLED_RECALL_UNDEFINED}
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        result = results[name]
        estimate = finite_or_none(result.estimate)
        low, high = finite_or_none(result.ci_low), finite_or_none(result.ci_high)
        if estimate is None:
            status = undefined[name]
        elif low is None or high is None:
            status = "no finite replicate: every resample had a zero denominator"
        else:
            status = "ok"
        out[name] = {
            **base,
            "estimate": estimate,
            "ci_low": low,
            "ci_high": high,
            "n_clusters": result.n_clusters,
            "n_dropped": result.n_nonfinite,
            "status": status,
        }
    return out


def _pooled(
    run: JudgeRun, items: Sequence[JudgeItem], types: Collection[str] | None
) -> dict[str, Any]:
    records = detection_records(run, items, types)
    entry = _counts(_tally(records), POOLED_PRECISION_UNDEFINED, POOLED_RECALL_UNDEFINED)
    entry["types"] = (
        sorted(types) if types is not None else sorted({r["claim_type"] for r in records})
    )
    entry["bootstrap"] = bootstrap_detection(records)
    return entry


def score_judge(
    run: JudgeRun, items: Sequence[JudgeItem], valid_types: ValidTypes | None = None
) -> dict[str, Any]:
    """Validity of one judge against the ledger over ``items`` (the scored runs).

    Per claim type and pooled (``pooled.valid_types``, the headline estimate, and
    ``pooled.all_types``), as the module docstring describes; ``valid_type`` and
    ``pooled.valid_types`` are None without a held-out evaluation.
    """
    labels = _labels(run)
    wanted = {item.run_id for item in items}
    served = [c for c in run.calls if c.served and c.run_id in wanted]
    rows = [
        (claim.claim_type, claim.verdict, labels.get((item.run_id, claim.claim_id)))
        for item in items
        for claim in item.claims
    ]
    valid = set(valid_types.types) if valid_types is not None else None
    per_type = {}
    for ctype, counts in score_detection(rows).items():
        entry = _counts(counts, PRECISION_UNDEFINED, RECALL_UNDEFINED)
        entry["valid_type"] = None if valid is None else ctype in valid
        per_type[ctype] = entry
    return {
        "judge_id": run.config.judge_id,
        "model": run.config.model,
        "backend": run.config.backend,
        "config": describe_config(run.config),
        "synthetic": run.synthetic,
        "calls": len(served),
        "calls_excluded": sum(1 for c in run.calls if not c.served),
        "parse_failures": sum(1 for c in served if c.status != "ok"),
        "parse_failure_kinds": dict(
            sorted(Counter(c.status for c in served if c.status != "ok").items())
        ),
        "claims": len(rows),
        "claims_unlabeled": sum(1 for _, _, judged in rows if judged is None),
        "label_counts": dict(
            sorted(Counter(judged or "unlabeled" for _, _, judged in rows).items())
        ),
        "per_type": per_type,
        "pooled": {
            "valid_types": None if valid is None else _pooled(run, items, valid),
            "all_types": _pooled(run, items, None),
        },
        "usage": {
            "input_tokens": sum(c.input_tokens for c in served),
            "output_tokens": sum(c.output_tokens for c in served),
            "wall_s": round(sum(c.wall_s for c in served), 3),
            "cache_hits": sum(1 for c in served if c.cache_hit),
        },
    }


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Cohen's kappa of two raters' labels, ``(p_o - p_e) / (1 - p_e)``; None when undefined."""
    n = len(pairs)
    if n == 0:
        return {
            "n": 0,
            "observed_agreement": None,
            "expected_agreement": None,
            "kappa": None,
            "status": "no claims labeled by both judges",
        }
    observed = sum(1 for a, b in pairs if a == b) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[k] * second[k] for k in set(first) | set(second)) / (n * n)
    if expected >= 1.0:
        kappa, status = None, "undefined: chance agreement is 1 (both judges used one label)"
    else:
        kappa, status = (observed - expected) / (1.0 - expected), "ok"
    return {
        "n": n,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "kappa": kappa,
        "status": status,
    }


def agreement(runs: Sequence[JudgeRun], items: Sequence[JudgeItem]) -> dict[str, Any]:
    """Pairwise agreement between judges (reliability), never a substitute for validity.

    Cohen's kappa on the three-way labels of the claims both judges labeled; Cohen's
    kappa on the contradicted flag over every claim (unlabeled counts as not flagged);
    and the claims both judges flag, with the number the ledger contradicts and the
    precision of that set.
    """
    keys = [(item.run_id, c.claim_id) for item in items for c in item.claims]
    truth = {(item.run_id, c.claim_id): c.verdict for item in items for c in item.claims}
    labels = {run.config.judge_id: _labels(run) for run in runs}
    pairs: list[dict[str, Any]] = []
    for a, b in itertools.combinations(runs, 2):
        la, lb = labels[a.config.judge_id], labels[b.config.judge_id]
        both = [(la[k], lb[k]) for k in keys if k in la and k in lb]
        flags = [
            (
                "contradicted" if la.get(k) == "contradicted" else "not flagged",
                "contradicted" if lb.get(k) == "contradicted" else "not flagged",
            )
            for k in keys
        ]
        consensus = [k for k in keys if la.get(k) == "contradicted" and lb.get(k) == "contradicted"]
        tp = sum(1 for k in consensus if truth[k] == "contradicted")
        pairs.append(
            {
                "judges": [a.config.judge_id, b.config.judge_id],
                "n_claims": len(keys),
                "three_way": cohen_kappa(both),
                "contradicted_flag": cohen_kappa(flags),
                "both_flagged": {
                    "claims": len(consensus),
                    "tp": tp,
                    "fp": len(consensus) - tp,
                    "precision": _metric(tp, len(consensus), "undefined: no claim flagged by both"),
                },
            }
        )
    return {"note": AGREEMENT_NOTE, "pairs": pairs}


# Exploratory analyses (section 6) ----------------------------------------------------------


def mechanism_classes(data: object) -> dict[tuple[str, str], str]:
    """``{(run_id, claim_id): class}`` from ``artifacts/e2/mechanism.json`` (``claims[]``).

    Raises:
        ValueError: There is no claims list, an entry lacks a run id, a claim id, or a
            known class, or a claim is classified twice.
    """
    claims = data.get("claims") if isinstance(data, Mapping) else None
    if not isinstance(claims, list):
        raise ValueError("the E2 mechanism artifact has no claims list")
    out: dict[tuple[str, str], str] = {}
    for index, entry in enumerate(claims):
        if (
            not isinstance(entry, Mapping)
            or not _is_text(entry.get("run_id"))
            or not _is_text(entry.get("claim_id"))
            or entry.get("class") not in MECHANISM_CLASSES
        ):
            raise ValueError(
                f"the E2 mechanism artifact's claims[{index}] lacks a run_id, a claim_id, or a "
                "known class"
            )
        key = (str(entry["run_id"]), str(entry["claim_id"]))
        if key in out:
            raise ValueError(f"the E2 mechanism artifact classifies claim {key} twice")
        out[key] = str(entry["class"])
    return out


def _group(
    run: JudgeRun, items: Sequence[JudgeItem], valid: Sequence[str] | None
) -> dict[str, Any]:
    """Counts with Wilson intervals over every type and over the valid types."""

    def entry(types: Collection[str] | None) -> dict[str, Any]:
        records = detection_records(run, items, types)
        return _counts(_tally(records), POOLED_PRECISION_UNDEFINED, POOLED_RECALL_UNDEFINED)

    return {"all_types": entry(None), "valid_types": None if valid is None else entry(valid)}


def _recall_by_mechanism(
    run: JudgeRun,
    items: Sequence[JudgeItem],
    classes: Mapping[tuple[str, str], str] | None,
) -> dict[str, Any]:
    if classes is None:
        return {
            "status": "not read: no E2 mechanism artifact was given",
            "classes": None,
            "unclassified": None,
        }
    labels = _labels(run)
    tallies = {name: [0, 0] for name in MECHANISM_CLASSES}
    unclassified = 0
    for item in items:
        for claim in item.claims:
            if claim.verdict != "contradicted":
                continue
            name = classes.get((item.run_id, claim.claim_id))
            if name is None:
                unclassified += 1
                continue
            tallies[name][0] += 1
            tallies[name][1] += labels.get((item.run_id, claim.claim_id)) == "contradicted"
    return {
        "status": "ok",
        "classes": {
            name: {
                "contradicted": n,
                "tp": tp,
                "recall": _metric(tp, n, "undefined: no ledger-contradicted claim of this class"),
            }
            for name, (n, tp) in tallies.items()
        },
        "unclassified": unclassified,
    }


def exploratory(
    runs: Sequence[JudgeRun],
    items: Sequence[JudgeItem],
    valid_types: ValidTypes | None,
    classes: Mapping[tuple[str, str], str] | None,
) -> dict[str, Any]:
    """The exploratory analyses of section 6, labeled EXPLORATORY.

    Per judge: counts, precision, and recall (Wilson intervals) by E1 arm and on runs of
    the judge's own model family against the other family, each over every type and over
    the valid types; and recall by the E2 mechanism class of each ledger-contradicted
    claim of every type (``classes`` from :func:`mechanism_classes`; claims the E2
    artifact does not classify are counted as ``unclassified``).
    """
    valid = sorted(valid_types.types) if valid_types is not None else None
    arms = sorted({item.config_id for item in items})
    out: dict[str, Any] = {}
    for run in runs:
        pin = LOCAL_MODELS.get(run.config.model)
        family = pin.family if pin is not None else None
        out[run.config.judge_id] = {
            "by_arm": {
                arm: _group(run, [i for i in items if i.config_id == arm], valid) for arm in arms
            },
            "by_family": {
                "judge_family": family,
                "own": _group(run, [i for i in items if i.model_family == family], valid),
                "other": _group(run, [i for i in items if i.model_family != family], valid),
            },
            "recall_by_mechanism": _recall_by_mechanism(run, items, classes),
        }
    return {"label": "EXPLORATORY", "note": EXPLORATORY_NOTE, "judges": out}


# Dry run ----------------------------------------------------------------------------------


def plan_calls(
    configs: Sequence[JudgeConfig],
    items: Sequence[JudgeItem],
    *,
    is_cached: Callable[[ModelRequest], bool] | None = None,
    context_tokens: int = CONTEXT_TOKENS,
    skip: Collection[str] = (),
) -> dict[str, Any]:
    """Count the calls a run would make, without calling any model (``--dry-run``).

    Input tokens are estimated as characters / :data:`CHARS_PER_TOKEN` per call (an
    approximation); output tokens are bounded by each call's ``max_tokens``. A call
    whose estimate plus ``max_tokens`` exceeds ``context_tokens`` is counted as one that
    may not fit the served context. Runs in ``skip`` (excluded) make no call.
    """
    with_claims = [item for item in items if item.claims]
    judged = [item for item in with_claims if item.run_id not in skip]
    judges: list[dict[str, Any]] = []
    for config in configs:
        requests = [judge_request(config, item) for item in judged]
        estimates = [
            math.ceil(sum(len(m["content"]) for m in r.messages) / CHARS_PER_TOKEN)
            for r in requests
        ]
        raw = config.params.get("max_tokens", 0)
        max_out = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
        cached = sum(1 for r in requests if is_cached is not None and is_cached(r))
        judges.append(
            {
                "judge_id": config.judge_id,
                "model": config.model,
                "calls": len(requests),
                "cached": cached,
                "new": len(requests) - cached,
                "estimated_input_tokens": sum(estimates),
                "mean_input_tokens": sum(estimates) / len(estimates) if estimates else None,
                "max_output_tokens": max_out * len(requests),
                "over_context_estimate": sum(1 for e in estimates if e + max_out > context_tokens),
            }
        )
    return {
        "runs": len(items),
        "runs_excluded": len(with_claims) - len(judged),
        "judges": judges,
        "total_calls": sum(j["calls"] for j in judges),
        "total_new": sum(j["new"] for j in judges),
        "context_tokens": context_tokens,
        "estimate": f"input tokens are characters / {CHARS_PER_TOKEN:g}; output tokens are "
        "the max_tokens cap of each call",
    }


# Confirmatory rules (section 8) -------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """What an E3 run read and how it was asked to run: the inputs of its artifact and rules.

    Attributes:
        rows: Every row of ``artifacts/e1/runs.jsonl``.
        sample: The sample drawn (None when none could be drawn).
        prereg: The cited preregistration, after the LOCK entry's commit was checked
            (``results_e4.committed_status``); None when none is cited.
        prereg_lines: ``(sample_runs, sample_seed)`` of its machine-readable lines.
        configs: The judges asked to run.
        limit: The ``--limit`` used, or None.
        valid_types: The valid types and the evaluated instrument from the held-out G5
            evaluation, or None when it was not read.
        rows_sha256: SHA-256 of the rows file's bytes.
        analyzed_rows_sha256: The SHA-256 of ``artifacts/e1/runs.jsonl`` that
            ``artifacts/e1/results.json`` records (:func:`analyzed_rows_sha256`).
        code_problems: Reasons from git that the analysis code or the inputs are not
            committed (``tools/run_judges.py``).
        deviations: Further deviations to report (an analysis code change after the
            freeze commit, for example).
        exclusions: The unservable calls by excluded run id (:func:`unservable_calls`).
        classes: E2 mechanism classes for the exploratory recall split, or None.
    """

    rows: tuple[Mapping[str, Any], ...] = ()
    sample: Sample | None = None
    prereg: PreregStatus | None = None
    prereg_lines: tuple[int | None, int | None] = (None, None)
    configs: tuple[JudgeConfig, ...] = JUDGES
    limit: int | None = None
    valid_types: ValidTypes | None = None
    rows_sha256: str | None = None
    analyzed_rows_sha256: str | None = None
    code_problems: tuple[str, ...] = ()
    deviations: tuple[Mapping[str, Any], ...] = ()
    exclusions: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    classes: Mapping[tuple[str, str], str] | None = None

    @property
    def sample_preregistered(self) -> bool:
        """Whether the sample was drawn with the K and the seed of the preregistration."""
        k, seed = self.prereg_lines
        return (
            self.sample is not None
            and k is not None
            and seed is not None
            and (self.sample.sample_runs, self.sample.seed) == (k, seed)
        )


def analyzed_rows_sha256(results: object, rel: str = ROWS) -> str | None:
    """The SHA-256 of ``rel`` that ``artifacts/e1/results.json`` records in its inputs.

    ``tools/analyze.py`` records every input's digest under ``provenance.inputs``. None
    when the artifact records none, or not as 64 lowercase hex digits.
    """
    prov = results.get("provenance") if isinstance(results, Mapping) else None
    inputs = prov.get("inputs") if isinstance(prov, Mapping) else None
    value = inputs.get(rel) if isinstance(inputs, Mapping) else None
    return value if isinstance(value, str) and _SHA256.match(value) else None


def _listed(ids: Sequence[str]) -> str:
    return ", ".join(ids[:5]) + (", ..." if len(ids) > 5 else "")


def _sample_problems(context: Context, items: Sequence[JudgeItem]) -> list[str]:
    """Condition 2: the preregistered sample, from the analyzed rows, with no --limit."""
    problems: list[str] = []
    k, seed = context.prereg_lines
    if k is None:
        problems.append("the preregistration has no machine-readable sample_runs line (section 3)")
    if seed is None:
        problems.append("the preregistration has no machine-readable sample_seed line (section 3)")
    sample = context.sample
    if sample is None:
        problems.append("no sample was drawn")
    elif k is not None and seed is not None and (sample.sample_runs, sample.seed) != (k, seed):
        problems.append(
            f"the sample was drawn with K = {sample.sample_runs} and seed {sample.seed}, not the "
            f"preregistered K = {k} and seed {seed}"
        )
    if context.limit is not None:
        problems.append(f"a --limit run (--limit {context.limit}) judges only part of the sample")
    if k is not None and seed is not None:
        try:
            expected = draw_sample(context.rows, k, seed)
        except ValueError as exc:
            problems.append(f"the preregistered sample cannot be drawn: {exc}")
        else:
            if sorted(item.run_id for item in items) != list(expected.run_ids):
                problems.append(
                    "the judged runs are not the preregistered sample drawn from the rows"
                )
    arms = sorted({str(row.get("config_id")) for row in context.rows})
    if arms != sorted(E1_ARMS):
        problems.append(
            f"the sampling frame's arms are {', '.join(arms) or 'none'}, not the four E1 arms "
            f"{', '.join(E1_ARMS)} (prereg 0001 section 3)"
        )
    if context.rows_sha256 is None:
        problems.append(f"the SHA-256 of {ROWS} is unknown")
    elif context.analyzed_rows_sha256 is None:
        problems.append(
            f"{E1_RESULTS} records no SHA-256 of {ROWS}, so the rows it analyzes are unknown"
        )
    elif context.rows_sha256 != context.analyzed_rows_sha256:
        problems.append(
            f"{ROWS} is not the file {E1_RESULTS} analyzes (its SHA-256 differs from the one "
            "recorded there)"
        )
    return problems


def _judge_problems(
    configs: Sequence[JudgeConfig], servers: Mapping[str, Mapping[str, Any]] | None
) -> list[str]:
    """Condition 3: both judges, each once and as configured, on their pinned model files."""
    problems: list[str] = []
    names = [c.judge_id for c in configs]
    expected = [j.judge_id for j in JUDGES]
    if sorted(names) != sorted(expected):
        problems.append(
            f"the judges are {', '.join(names) or 'none'}, not exactly the preregistered "
            f"{', '.join(expected)}, each once"
        )
    preregistered = {j.judge_id: j for j in JUDGES}
    for config in configs:
        if config.judge_id in preregistered and config != preregistered[config.judge_id]:
            problems.append(
                f"judge {config.judge_id} is not configured as preregistered "
                "(prereg 0003 section 4)"
            )
    if servers is not None:
        for config in configs:
            server = servers.get(config.judge_id)
            pin = LOCAL_MODELS.get(config.model)
            if (
                pin is None
                or not isinstance(server, Mapping)
                or server.get("model") != config.model
                or server.get("model_sha256") != pin.sha256
            ):
                problems.append(
                    f"judge {config.judge_id}: its server provenance does not record the pinned "
                    f"model file SHA-256 of {config.model}"
                )
    return problems


def _completeness_problems(
    context: Context, items: Sequence[JudgeItem], runs: Sequence[JudgeRun]
) -> list[str]:
    """Condition 4: every sampled run judged by both judges, apart from excluded runs."""
    wanted = [i.run_id for i in items if i.claims and i.run_id not in context.exclusions]
    problems: list[str] = []
    ran = {run.config.judge_id for run in runs}
    for config in context.configs:
        if config.judge_id not in ran:
            problems.append(f"judge {config.judge_id} did not run")
    for run in runs:
        served = {c.run_id for c in run.calls if c.served}
        missing = [run_id for run_id in wanted if run_id not in served]
        if missing:
            problems.append(
                f"judge {run.config.judge_id} did not judge {len(missing)} sampled run(s): "
                f"{_listed(missing)}"
            )
    return problems


def _instrument_problems(context: Context) -> list[str]:
    """Condition 6: the held-out evaluation, and frame rows from the evaluated instrument."""
    valid = context.valid_types
    if valid is None:
        return [
            f"the held-out G5 evaluation ({SEEDED_EVAL}) was not read, so the valid types are "
            "unknown"
        ]
    recorded = valid.instrument.get("trees") or {}
    if not recorded:
        return ["the held-out G5 evaluation records no instrument trees"]
    # A row binds the trees of the paths re-verification runs (DECISIONS D47).
    evaluated = bound_trees(recorded)
    frame = [row for row in context.rows if in_frame(row)]
    other: list[str] = []
    dirty: list[str] = []
    for row in frame:
        instrument = row.get("instrument")
        trees = instrument.get("trees") if isinstance(instrument, Mapping) else None
        if not isinstance(trees, Mapping) or dict(trees) != evaluated:
            other.append(str(row["run_id"]))
        if row.get("instrument_dirty") is not False:
            dirty.append(str(row["run_id"]))
    problems: list[str] = []
    if other:
        problems.append(
            f"{len(other)} row(s) of the sampling frame record instrument trees other than the "
            f"evaluated ones (prereg 0001 section 5): {_listed(other)}"
        )
    if dirty:
        problems.append(
            f"{len(dirty)} row(s) of the sampling frame are instrument_dirty (banked from "
            f"uncommitted code): {_listed(dirty)}"
        )
    return problems


def confirmatory_problems(
    context: Context,
    items: Sequence[JudgeItem],
    *,
    runs: Sequence[JudgeRun] | None = None,
    servers: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Why the artifact may not be confirmatory (empty when it may), by section 8's list.

    1. The preregistration is frozen in ``prereg/LOCK.json`` with its current SHA-256, in
       an intact chain, with the LOCK entry committed (``context.prereg``).
    2. The judged runs are exactly the sample of section 3, drawn with the K and the seed
       of the machine-readable lines from the rows that ``artifacts/e1/results.json``
       analyzes (the rows file's SHA-256 equals the one recorded there), with no
       ``--limit``; the rows have the four E1 arms.
    3. Both judges of :data:`JUDGES`, each once and exactly as configured; with
       ``servers``, each judge's server provenance records its model and the pinned
       model file SHA-256.
    4. With ``runs``: each judge ran and judged every sampled run, apart from runs
       excluded under section 7.
    5. No judged run is synthetic; with ``runs``, no judge is synthetic.
    6. The held-out G5 evaluation was read, and every row of the sampling frame records
       the evaluated instrument trees of the bound paths
       (:func:`receipts.study.rescore.bound_trees`) and is not ``instrument_dirty``.
    7. The analysis code has no uncommitted change (``context.code_problems``, from git).

    Before any call, ``runs`` and ``servers`` are None and conditions 3 (servers), 4, and
    5 (judges) are checked later, by :func:`judges_artifact`.
    """
    problems: list[str] = []
    prereg = context.prereg
    if prereg is None:
        problems.append("no preregistration is cited")
    else:
        problems.extend(f"preregistration: {p}" for p in prereg.problems)
        if not prereg.frozen and not prereg.problems:
            problems.append(f"preregistration: {prereg.path} is not frozen")
    problems.extend(_sample_problems(context, items))
    problems.extend(_judge_problems(context.configs, servers))
    if not items:
        problems.append("no judged runs")
    if runs is not None:
        problems.extend(_completeness_problems(context, items, runs))
    synthetic = sum(1 for item in items if item.synthetic)
    if synthetic:
        problems.append(f"{synthetic} judged run(s) are synthetic")
    fake = [run.config.judge_id for run in runs or () if run.synthetic]
    if fake:
        problems.append("synthetic judge(s): " + ", ".join(fake))
    problems.extend(_instrument_problems(context))
    problems.extend(context.code_problems)
    return problems


# The artifact (section 8) ----------------------------------------------------------------


def reply_records(runs: Sequence[JudgeRun], excluded: Collection[str] = ()) -> list[dict[str, Any]]:
    """One record per served call for ``artifacts/e3/replies.jsonl`` (section 8), which
    follow its first record (:func:`replies_header`).

    Each holds the judge id, run id, cache key, cache hit, the raw reply text, its parse
    status, finish reason, tokens, wall time, and whether the run is excluded, so every
    label can be checked against what the judge said, and a re-score
    (:class:`BankedReplies`) can serve the call again without a model.
    """
    return [
        {
            "judge_id": run.config.judge_id,
            "run_id": call.run_id,
            "cache_key": call.cache_key,
            "cache_hit": call.cache_hit,
            "text": call.text,
            "status": call.status,
            "finish_reason": call.finish_reason,
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "wall_s": call.wall_s,
            "excluded": call.run_id in excluded,
        }
        for run in runs
        for call in run.calls
        if call.served
    ]


def replies_header(
    servers: Mapping[str, Mapping[str, Any]], failure_log: tuple[str, str] | None
) -> dict[str, Any]:
    """The first record of the replies file: what the artifact takes from the run that
    git holds nowhere else (section 8; DECISIONS D65).

    ``model_servers`` is each judge's model server provenance as the artifact records it
    under ``provenance.model_servers`` (the pinned model file, the server command, and
    whether the server started, which depends on the run's response cache).
    ``failure_log`` is the ``path`` and ``text`` of the failure log the run read (section
    7), or None when there was none: the log lives under ``runs/``, which git ignores,
    and the exclusions and the log's input hash come from it.
    """
    return {
        "schema": REPLIES_SCHEMA,
        "model_servers": {judge: dict(server) for judge, server in servers.items()},
        "failure_log": None
        if failure_log is None
        else {"path": failure_log[0], "text": failure_log[1]},
    }


def jsonl_objects(text: str, where: str) -> list[dict[str, Any]]:
    """The JSON objects of JSONL ``text``, one per non-blank line, in order.

    Lines are split on ``\\n`` only (a JSON string holding U+2028 stays one line) and the
    text is read as it is, so the failure log parses the same from its file and from the
    copy the replies file banks.

    Raises:
        ValueError: A line is not strict JSON (NaN and Infinity refused) or not an
            object; the message names ``where`` and the line number.
    """

    def refuse(constant: str) -> Any:
        raise ValueError(f"{constant} is not strict JSON")

    objects: list[dict[str, Any]] = []
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line, parse_constant=refuse)
        except ValueError as exc:  # json.JSONDecodeError included
            raise ValueError(f"{where} line {number} is not strict JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{where} line {number} is not a JSON object")
        objects.append(data)
    return objects


class MissingReplyError(ValueError):
    """A re-score met a judge request that no banked reply answers."""


_REPLY_TEXT_FIELDS = ("judge_id", "run_id", "text", "status", "finish_reason")
_REPLY_COUNT_FIELDS = ("input_tokens", "output_tokens")
_REPLY_FLAG_FIELDS = ("cache_hit", "excluded")


def _reply_record(record: Mapping[str, Any], where: str) -> dict[str, Any]:
    """A banked reply record (:func:`reply_records`), after its fields are checked.

    Raises:
        ValueError: A field is missing or of the wrong type, or the record carries a
            ``schema`` (only the first record does).
    """
    bad = [name for name in _REPLY_TEXT_FIELDS if not isinstance(record.get(name), str)]
    for name in _REPLY_COUNT_FIELDS:
        value = record.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            bad.append(name)
    bad += [name for name in _REPLY_FLAG_FIELDS if not isinstance(record.get(name), bool)]
    wall = record.get("wall_s")
    if isinstance(wall, bool) or not isinstance(wall, int | float) or not wall >= 0:
        bad.append("wall_s")
    key = record.get("cache_key")
    if not isinstance(key, str) or not _SHA256.match(key):
        bad.append("cache_key")
    if "schema" in record:
        bad.append("schema")
    if bad:
        raise ValueError(f"{where} is not a reply record: {', '.join(bad)} missing or malformed")
    return dict(record)


class BankedReplies:
    """An E3 run's replies file, read back to re-score the run without a model call.

    ``tools/run_judges.py --rescore`` passes :meth:`completion` to :func:`run_judge` for
    each judge in place of a model client, so every reply text, token count, wall time,
    finish reason, and cache hit is the banked one, while the labels, parse statuses, and
    every score are computed again by the code that runs. The judges' model server
    provenance and the failure log the run read come from the first record
    (:func:`replies_header`), and :meth:`check_served` requires every banked reply to
    have answered one call.

    Attributes:
        where: The file's name in messages.
        sha256: SHA-256 of the file's bytes.
        servers: Each judge's banked model server provenance, by judge id.
        failure_log: ``(path, text)`` of the failure log the run read, or None.
        records: The reply records, in file order.
    """

    def __init__(self, raw: bytes, where: str) -> None:
        """Parse and check the file's bytes ``raw``.

        Raises:
            ValueError: The bytes are not UTF-8 strict JSON lines, the first record is
                not a :data:`REPLIES_SCHEMA` record with ``model_servers`` and
                ``failure_log``, or a later record is not a reply record.
        """
        self.where = where
        self.sha256 = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{where} is not UTF-8 text ({exc.reason})") from exc
        objects = jsonl_objects(text, where)
        header = objects[0] if objects else {}
        if header.get("schema") != REPLIES_SCHEMA:
            raise ValueError(
                f"{where} does not begin with its {REPLIES_SCHEMA} record (the model servers "
                "and the failure log of the run), so it cannot be re-scored"
            )
        servers = header.get("model_servers")
        if not isinstance(servers, dict) or not all(isinstance(s, dict) for s in servers.values()):
            raise ValueError(
                f"{where}: the first record's model_servers is not an object of objects"
            )
        if "failure_log" not in header:
            raise ValueError(f"{where}: the first record has no failure_log")
        log = header["failure_log"]
        if log is None:
            self.failure_log: tuple[str, str] | None = None
        elif isinstance(log, dict) and all(isinstance(log.get(k), str) for k in ("path", "text")):
            self.failure_log = (log["path"], log["text"])
        else:
            raise ValueError(
                f"{where}: the first record's failure_log is neither null nor a path and a text"
            )
        self.servers: dict[str, dict[str, Any]] = {str(j): dict(s) for j, s in servers.items()}
        self.records: tuple[dict[str, Any], ...] = tuple(
            _reply_record(record, f"{where} reply {number}")
            for number, record in enumerate(objects[1:], start=1)
        )
        self._waiting: dict[tuple[str, str], list[int]] = {}
        for index, record in enumerate(self.records):
            self._waiting.setdefault((record["judge_id"], record["cache_key"]), []).append(index)
        self._served: dict[str, list[int]] = {}

    @classmethod
    def read(cls, path: Path, where: str) -> BankedReplies:
        """The replies file at ``path``, named ``where`` in messages.

        Raises:
            ValueError: The file is missing, or :class:`BankedReplies` refuses it.
            OSError: It cannot be read.
        """
        if not path.is_file():
            raise ValueError(
                f"{where} is missing: a re-score serves every judge call from the banked replies"
            )
        return cls(path.read_bytes(), where)

    def completion(self, judge_id: str) -> Completion:
        """A completion function that serves ``judge_id``'s requests from the banked replies.

        Each request gets the next unserved reply of that judge with the request's cache
        key, in file order, so two calls with the same request (two runs with the same
        transcript and claims) each get their own record, as they were made. The
        function raises :class:`MissingReplyError` when no unserved banked reply of the
        judge answers the request; it never calls a model.
        """
        served = self._served.setdefault(judge_id, [])

        def complete(request: ModelRequest) -> ModelResponse:
            key = request.cache_key()
            waiting = self._waiting.get((judge_id, key))
            if not waiting:
                raise MissingReplyError(
                    f"{self.where} has no banked reply of judge {judge_id} to request {key} "
                    f"({request.purpose or 'no purpose'})"
                )
            index = waiting.pop(0)
            served.append(index)
            record = self.records[index]
            return ModelResponse(
                text=record["text"],
                input_tokens=record["input_tokens"],
                output_tokens=record["output_tokens"],
                wall_s=record["wall_s"],
                finish_reason=record["finish_reason"],
                cache_hit=record["cache_hit"],
            )

        return complete

    def check_served(self, runs: Sequence[JudgeRun]) -> None:
        """Every banked reply answered exactly one call of ``runs``, about the run it records.

        Raises:
            ValueError: A reply answered a call about another run than the one it records,
                or banked replies answered no call (the file is not this run's replies).
        """
        for run in runs:
            judge = run.config.judge_id
            calls = [call for call in run.calls if call.served]
            served = self._served.get(judge, [])
            if len(served) != len(calls):
                raise ValueError(
                    f"{self.where}: {len(served)} banked replies of judge {judge} were served "
                    f"for {len(calls)} calls"
                )
            for call, index in zip(calls, served, strict=True):
                recorded = self.records[index]["run_id"]
                if recorded != call.run_id:
                    raise ValueError(
                        f"{self.where}: the banked reply of judge {judge} to request "
                        f"{call.cache_key} records run {recorded}, not run {call.run_id}"
                    )
        used = {index for indexes in self._served.values() for index in indexes}
        unused = [index for index in range(len(self.records)) if index not in used]
        if unused:
            first = self.records[unused[0]]
            raise ValueError(
                f"{self.where} holds {len(unused)} banked reply record(s) that answer no call "
                f"of this re-score (first: judge {first['judge_id']}, run {first['run_id']}), "
                "so it is not the replies file of this run"
            )


def _complete(
    context: Context, items: Sequence[JudgeItem], runs: Sequence[JudgeRun], excluded: set[str]
) -> bool:
    """``runs.complete``: the whole sample, both judges, every run judged or excluded."""
    sample = context.sample
    if sample is None or context.limit is not None:
        return False
    if sorted(run.config.judge_id for run in runs) != sorted(j.judge_id for j in JUDGES):
        return False
    ids = {item.run_id for item in items}
    if ids != set(sample.run_ids):
        return False
    wanted = ids - excluded
    return all(wanted <= {c.run_id for c in run.calls if c.served} for run in runs)


def _deviations(context: Context, excluded: Sequence[str]) -> list[dict[str, Any]]:
    """The deviations to report: the context's, each arm's shortfall, each exclusion."""
    out = [dict(d) for d in context.deviations]
    sample = context.sample
    short = [arm for arm in sample.arms if arm.shortfall] if sample is not None else []
    for arm in short:
        assert sample is not None  # for mypy: short is empty without a sample
        out.append(
            {
                "kind": "sample_shortfall",
                "prereg_section": "3",
                "config_id": arm.config_id,
                "eligible": len(arm.eligible),
                "per_arm": sample.per_arm,
                "shortfall": arm.shortfall,
                "detail": f"arm {arm.config_id} has {len(arm.eligible)} eligible run(s), "
                f"fewer than K/4 = {sample.per_arm}; it contributes all of them, and its "
                f"shortfall of {arm.shortfall} is not made up from other arms",
            }
        )
    for run_id in excluded:
        calls = context.exclusions[run_id]
        out.append(
            {
                "kind": "excluded_unservable",
                "prereg_section": "7",
                "run_id": run_id,
                "judges": [str(c.get("judge_id")) for c in calls],
                "detail": f"run {run_id} is excluded for both judges: a call of it could not be "
                f"served after {MAX_ATTEMPTS} attempts; it is not replaced",
            }
        )
    return out


def judges_artifact(
    context: Context,
    items: Sequence[JudgeItem],
    runs: Sequence[JudgeRun],
    *,
    provenance: Mapping[str, Any],
    servers: Mapping[str, Mapping[str, Any]] | None = None,
    replies: Mapping[str, Any] | None = None,
    confirmatory: bool = False,
) -> dict[str, Any]:
    """The ``artifacts/e3/judges.json`` artifact (module docstring; gate G8).

    Args:
        context: What the run read and how it was asked to run.
        items: The sampled runs judged (after any ``--limit``), sorted by run id.
        runs: One :class:`JudgeRun` per judge that ran.
        provenance: ``git_sha``, ``command``, ``created``, input hashes, and the rest.
        servers: Each judge's model server provenance, by judge id.
        replies: ``path``, ``sha256``, and ``records`` of the replies file.
        confirmatory: Mark the artifact confirmatory; refused unless
            :func:`confirmatory_problems` finds nothing.

    Raises:
        ConfirmatoryRefusedError: ``confirmatory`` was asked for and a rule is not met.
    """
    problems = confirmatory_problems(context, items, runs=runs, servers=servers or {})
    if confirmatory and problems:
        raise ConfirmatoryRefusedError(
            "refusing a confirmatory E3 artifact: " + "; ".join(problems)
        )
    sampled = {item.run_id for item in items}
    excluded = sorted(run_id for run_id in context.exclusions if run_id in sampled)
    scored = [item for item in items if item.claims and item.run_id not in excluded]
    valid = context.valid_types
    valid_set = set(valid.types) if valid is not None else None
    claim_types: dict[str, dict[str, Any]] = {}
    for item in scored:
        for claim in item.claims:
            entry = claim_types.setdefault(
                claim.claim_type,
                {
                    "claims": 0,
                    "contradicted": 0,
                    "valid_type": None if valid_set is None else claim.claim_type in valid_set,
                },
            )
            entry["claims"] += 1
            entry["contradicted"] += claim.verdict == "contradicted"
    labels = {run.config.judge_id: _labels(run) for run in runs}
    prereg = context.prereg
    sample = context.sample
    k, seed = context.prereg_lines
    artifact = {
        "schema": SCHEMA,
        "experiment": "E3",
        "question": "RQ4: how well do LLM judges that read the transcript detect the claims "
        "the ledger contradicts (precision and recall by claim type)?",
        "analysis": "confirmatory" if confirmatory else "exploratory",
        "confirmatory": confirmatory,
        "confirmatory_problems": problems,
        "prereg": prereg.path if prereg is not None else None,
        "prereg_sha256": prereg.sha256 if prereg is not None else None,
        "prereg_frozen": prereg.frozen if prereg is not None else False,
        "synthetic": any(i.synthetic for i in items) or any(r.synthetic for r in runs),
        "ground_truth": GROUND_TRUTH,
        "sample": None
        if sample is None
        else {
            **sample.as_dict(),
            "preregistered": context.sample_preregistered,
            "prereg_sample_runs": k,
            "prereg_sample_seed": seed,
        },
        "runs": {
            "rows": len(context.rows),
            "frame": sum(1 for row in context.rows if in_frame(row)),
            "sampled": len(sample.run_ids) if sample is not None else None,
            "judged": len(scored),
            "excluded": excluded,
            "limit": context.limit,
            "judges": [run.config.judge_id for run in runs],
            "complete": _complete(context, items, runs, set(excluded)),
        },
        "exclusions": [
            {"run_id": run_id, "calls": [dict(c) for c in context.exclusions[run_id]]}
            for run_id in excluded
        ],
        "claim_types": dict(sorted(claim_types.items())),
        "valid_claim_types": valid.as_dict() if valid is not None else None,
        "valid_type_note": VALID_TYPE_NOTE,
        "judges": [score_judge(run, scored, valid) for run in runs],
        "agreement": agreement(runs, scored),
        "exploratory": exploratory(runs, scored, valid, context.classes),
        "items": [
            {
                "run_id": item.run_id,
                "task_id": item.task_id,
                "config_id": item.config_id,
                "claim_id": claim.claim_id,
                "claim_type": claim.claim_type,
                "truth": claim.verdict,
                "labels": {j: labels[j].get((item.run_id, claim.claim_id)) for j in labels},
            }
            for item in scored
            for claim in item.claims
        ],
        "calls": [
            {
                "judge_id": run.config.judge_id,
                "run_id": call.run_id,
                "status": call.status,
                "served": call.served,
                "cache_key": call.cache_key,
                "cache_hit": call.cache_hit,
                "finish_reason": call.finish_reason,
            }
            for run in runs
            for call in run.calls
        ],
        "replies": dict(replies) if replies is not None else None,
        "deviations": _deviations(context, excluded),
        "provenance": {
            **dict(provenance),
            "prereg": prereg.path if prereg is not None else None,
            "prereg_sha256": prereg.sha256 if prereg is not None else None,
            "model_servers": {k2: dict(v) for k2, v in (servers or {}).items()},
        },
    }
    cleaned: dict[str, Any] = strict_json(artifact)
    return cleaned
