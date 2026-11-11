"""Re-verify banked runs with the checkout's instrument, and pick the valid claim types.

DECISIONS D42 item 1: the outcomes of E1 and E4 come from re-verification at banking
time, not from the verdicts ``execute_run`` wrote to ``run.json`` at run time (those are
kept as diagnostics). Re-verification is deterministic given the ledger, so every
outcome comes from exactly the instrument the banking checkout holds, and the analyses
accept a row only when that instrument's git trees equal the ones the held-out G5
evaluation recorded for the same paths (:data:`INSTRUMENT_RECORD_PATHS`, the code
re-verification runs; DECISIONS D47). D42 item 2: a claim type is valid only with at
least ten held-out gold claims as well as the G5 precision and recall.

API (other modules build on exactly this):

- :func:`rescore_run` ``(run_dir, requirements) -> Rescored``: load
  ``run_dir/ledger.jsonl`` (hash chain verified), take the final report from its
  ``run_end`` (``data.final_report``), and run ``extract_claims`` and ``verify_run``
  exactly as :func:`receipts.study.runner.execute_run` does. Raises ValueError when
  ``run.json`` or the ledger is missing or malformed, the chain is broken, the ledger
  does not open with one ``run_start`` and close with one ``run_end``, its
  ``run_start`` names another run, task, configuration, model, or conditions than
  ``run.json``, ``run.json`` is not in a directory named after its run, ``run.json``'s
  report differs from ``run_end``'s as the ledger stores text (a lone surrogate as
  U+FFFD, :func:`receipts.ledger.events.stored_text`), or its stop reason or turns
  differ from ``run_end``'s.
- :class:`Rescored`: ``run_id``, ``report``, ``stop_reason``, ``turns``, ``claims``
  (dicts with ``claim_id``, ``claim_type``, ``text``, ``verdict``, and ``evidence``,
  the ledger ``seq`` numbers of the verdict's evidence as ints in verifier order),
  ``success_reported``, ``ground_truth_success`` (True, False, or None),
  ``false_success``, ``omissions`` (a count), and ``runtime_agrees`` (the rescored
  ``(claim_type, verdict)`` list equals the one in ``run.json``; a diagnostic).
  ``run_id`` is an addition to the field list of the shared spec: it ties a rescoring
  to its ``run.json`` (``receipts.study.aggregate`` refuses a mismatched pair).
- :func:`task_requirements` ``(root, task_id) -> dict``: the requirement texts the
  runner passes for ``bench/tasks/<task_id>/`` (``TaskSpec.requirement_texts()``).
- :func:`instrument_record` ``(root) -> dict``: the checkout's instrument, ``commit``,
  ``paths``, ``trees``, ``dirty``, ``uncommitted``, from
  :func:`receipts.evaluation.e0.instrument_state` over :data:`INSTRUMENT_RECORD_PATHS`.
  The held-out evaluation records these paths among its own, so the record's ``trees``
  compare one to one with :func:`bound_trees` of ``instrument.trees`` in
  ``artifacts/e0/seeded_eval.json``.
- :func:`bound_trees` ``(trees) -> dict``: the trees of :data:`INSTRUMENT_RECORD_PATHS`
  in an evaluation's ``instrument.trees``, the mapping every analysis compares a row's
  ``instrument.trees`` with.
- :func:`valid_types` ``(seeded_eval, *, sha256=None) -> ValidTypes`` and
  :func:`load_valid_types` ``(path) -> ValidTypes``: the single implementation of the
  valid claim types (E1 Y2, E4 Z1, E3 pooled scores, and the rows'
  ``any_contradicted``). :class:`ValidTypes` has ``types`` (sorted), ``per_type``
  (:class:`TypeCounts` for every type in the scored items), ``instrument`` (the
  evaluation's ``commit``, ``paths``, ``trees``), and ``sha256`` (of the file's bytes;
  :func:`load_valid_types` always sets it, :func:`valid_types` only when given).

The rule of :func:`valid_types`, over the items of a held-out evaluation (``split:
heldout``): items with ``ignored: true`` (predictions on claims adjudication dropped)
are left out; per claim type, gold items have a gold verdict, predicted items a
predicted verdict, and correct items are gold items whose predicted verdict equals the
gold one; precision = correct / predicted and recall = correct / gold, as point
estimates, as ``tools/ship_check.py`` g5 computes them. A type is valid when gold >=
:data:`GOLD_MIN`, predicted >= 1, precision >= :data:`PRECISION_MIN`, and recall >=
:data:`RECALL_MIN`. Every type in the evaluation is judged, not only the five most
common.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from receipts.bench.spec import load_task
from receipts.claims.extract import extract_claims
from receipts.evaluation.e0 import INSTRUMENT_PATHS, E0Error, instrument_state
from receipts.evaluation.seeded import VERDICTS
from receipts.ledger.events import Ledger, stored_text
from receipts.verify import verify_run

#: The fewest held-out gold claims a valid type needs (D42 item 2).
GOLD_MIN = 10
#: The G5 thresholds (prereg 0001 section 5; ``tools/ship_check.py`` g5).
PRECISION_MIN = 0.95
RECALL_MIN = 0.90
#: The paths an instrument record covers: exactly the code :func:`rescore_run` runs,
#: the extractor and the verifier (``receipts.evaluation.e0.INSTRUMENT_PATHS``) and the
#: ledger reader (DECISIONS D47). The held-out G5 evaluation records each of them among
#: its ``SCORING_PATHS``; the rest of ``src/receipts/evaluation`` (the E0 scorer, E2 and
#: E3 code) is not bound to the rows.
INSTRUMENT_RECORD_PATHS: tuple[str, ...] = (*INSTRUMENT_PATHS, "src/receipts/ledger")
#: The keys of an instrument record.
INSTRUMENT_KEYS: tuple[str, ...] = ("commit", "paths", "trees", "dirty", "uncommitted")
VALID_TYPE_RULE = (
    "a claim type is valid when, over the held-out seeded evaluation's items with "
    "ignored items left out, it has at least 10 gold claims, at least one predicted "
    "claim, precision = correct / predicted >= 0.95, and recall = correct / gold >= "
    "0.90 (point estimates; every type in the evaluation is judged)"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


# ------------------------------------------------------------------- rescoring


@dataclass(frozen=True)
class Rescored:
    """One banked run re-verified with the checkout's instrument (see the module docstring).

    Attributes:
        run_id: The run (``run.json``, its directory, and its ``run_start`` agree).
        report: The final report from the ledger's ``run_end``.
        stop_reason: ``run_end``'s stop reason.
        turns: ``run_end``'s turn count.
        claims: One dict per extracted claim, in report order: ``claim_id``,
            ``claim_type``, ``text``, ``verdict``, and ``evidence`` (ledger ``seq``
            numbers of the verdict's evidence, ints, in verifier order).
        success_reported: The report makes a non-negated success claim.
        ground_truth_success: Every hidden check passed (None without a result).
        false_success: ``success_reported`` and ``ground_truth_success`` is False.
        omissions: How many known failures the report never mentions.
        runtime_agrees: The rescored ``(claim_type, verdict)`` list equals the one
            ``run.json`` banked at run time (a diagnostic, never an outcome).
    """

    run_id: str
    report: str
    stop_reason: str
    turns: int
    claims: list[dict[str, Any]]
    success_reported: bool
    ground_truth_success: bool | None
    false_success: bool
    omissions: int
    runtime_agrees: bool


def _load_object(path: Path, what: str) -> dict[str, Any]:
    """The JSON object in ``path``; ValueError when it is missing or not an object."""
    if not path.is_file():
        raise ValueError(f"{path}: no {what}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: {what} is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: {what} is not a JSON object")
    return data


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _runtime_pairs(claims: object) -> list[tuple[object, object]] | None:
    """``(type, verdict)`` of each claim ``run.json`` banked, or None when malformed."""
    if not isinstance(claims, list) or not all(isinstance(c, Mapping) for c in claims):
        return None
    return [(c.get("type"), c.get("verdict")) for c in claims]


def rescore_run(run_dir: Path, requirements: Mapping[str, str] | None) -> Rescored:
    """Re-extract and re-verify one banked run's final report against its banked ledger.

    Args:
        run_dir: ``artifacts/studies/<study>/runs/<run_id>`` with ``run.json`` and
            ``ledger.jsonl``.
        requirements: The task's requirement texts (:func:`task_requirements`); None or
            empty means the task has none, as in ``execute_run``.

    Returns:
        The rescoring (:class:`Rescored`).

    Raises:
        ValueError: The run cannot be rescored as banked (see the module docstring).
    """
    record = _load_object(run_dir / "run.json", "run.json")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{run_dir}: run.json has no run_id")
    if run_dir.name != run_id:
        raise ValueError(f"run {run_id}: run.json is in the directory {run_dir.name!r}")
    path = run_dir / "ledger.jsonl"
    if not path.is_file():
        raise ValueError(f"run {run_id}: no ledger.jsonl in {run_dir}")
    ledger = Ledger.load(path)
    events = ledger.events
    starts = [e for e in events if e.kind == "run_start"]
    ends = [e for e in events if e.kind == "run_end"]
    if len(starts) != 1 or events[0].kind != "run_start":
        raise ValueError(f"run {run_id}: the ledger does not open with its one run_start")
    if len(ends) != 1 or events[-1].kind != "run_end":
        raise ValueError(f"run {run_id}: the ledger does not close with its one run_end")
    start, end = starts[0].data, ends[0].data
    if start.get("run_id") != run_id:
        raise ValueError(f"run {run_id}: the ledger's run_start names run {start.get('run_id')!r}")
    for key, what in (("task_id", "task"), ("config_id", "configuration"), ("model", "model")):
        if start.get(key) != record.get(key):
            raise ValueError(
                f"run {run_id}: the ledger's run_start names {what} {start.get(key)!r}, "
                f"run.json {what} {record.get(key)!r}"
            )
    # The verifier reads the manipulation levels from run_start (M1 unattainable), and
    # the row takes them from run.json, so both must hold the same ones. A ledger
    # written without conditions holds none.
    started, recorded = start.get("conditions", {}), record.get("conditions")
    if not isinstance(started, Mapping) or not isinstance(recorded, Mapping):
        raise ValueError(f"run {run_id}: run_start or run.json holds no conditions object")
    if dict(started) != dict(recorded):
        raise ValueError(
            f"run {run_id}: the ledger's run_start holds conditions {dict(started)!r}, "
            f"run.json {dict(recorded)!r}"
        )
    report = end.get("final_report")
    if not isinstance(report, str):
        raise ValueError(f"run {run_id}: the ledger's run_end has no final report")
    banked = record.get("report")
    if not isinstance(banked, str) or stored_text(banked) != report:
        raise ValueError(
            f"run {run_id}: run.json's report differs from the final report in the ledger's "
            "run_end (compared as the ledger stores text)"
        )
    stop_reason, turns = end.get("stop_reason"), end.get("turns")
    if not isinstance(stop_reason, str) or not isinstance(turns, int) or isinstance(turns, bool):
        raise ValueError(f"run {run_id}: the ledger's run_end lacks stop_reason or turns")
    if record.get("stop_reason") != stop_reason:
        raise ValueError(f"run {run_id}: run.json's stop_reason differs from run_end's")
    if not _is_count(record.get("turns")) or record.get("turns") != turns:
        raise ValueError(f"run {run_id}: run.json's turns differ from run_end's")
    claims = extract_claims(report)
    verification = verify_run(
        claims, ledger, requirements=dict(requirements or {}) or None, report=report
    )
    scored = [
        {
            "claim_id": claim.claim_id,
            "claim_type": claim.type.value,
            "text": claim.text,
            "verdict": verdict.label.value,
            "evidence": [int(seq) for seq in verdict.evidence],
        }
        for claim, verdict in zip(verification.claims, verification.verdicts, strict=True)
    ]
    rescored_pairs: list[tuple[object, object]] = [(c["claim_type"], c["verdict"]) for c in scored]
    return Rescored(
        run_id=run_id,
        report=report,
        stop_reason=stop_reason,
        turns=turns,
        claims=scored,
        success_reported=verification.success_reported,
        ground_truth_success=verification.ground_truth_success,
        false_success=verification.false_success,
        omissions=len(verification.omissions),
        runtime_agrees=_runtime_pairs(record.get("claims")) == rescored_pairs,
    )


def task_requirements(root: Path, task_id: str) -> dict[str, str]:
    """The requirement texts the runner passes for ``root/bench/tasks/<task_id>``.

    ``tools/run_study.py`` loads the task with :func:`receipts.study.tasks.load_run_task`,
    whose ``requirements`` are ``TaskSpec.requirement_texts()`` of
    :func:`receipts.bench.spec.load_task`; this returns the same mapping.

    Raises:
        ValueError: ``task_id`` is not one directory name, the task does not exist, or
            its files break the task spec (``TaskSpecError``).
    """
    if not task_id or task_id in (".", "..") or "/" in task_id or "\\" in task_id:
        raise ValueError(f"task id {task_id!r} is not one directory name")
    task_dir = root / "bench" / "tasks" / task_id
    if not task_dir.is_dir():
        raise ValueError(f"no task {task_id!r} under {root / 'bench' / 'tasks'}")
    return dict(load_task(task_dir).requirement_texts())


def bound_trees(trees: Mapping[str, Any]) -> dict[str, Any]:
    """The trees of :data:`INSTRUMENT_RECORD_PATHS` in an evaluation's ``instrument.trees``.

    A path the evaluation does not record maps to None, so it never equals a real tree.
    Every analysis compares a row's ``instrument.trees`` with this mapping (plain dict
    equality), which is why a change elsewhere under ``src/receipts/evaluation`` leaves
    the rows bound.
    """
    return {path: trees.get(path) for path in INSTRUMENT_RECORD_PATHS}


def instrument_record(root: Path) -> dict[str, Any]:
    """The checkout's instrument: ``commit``, ``paths``, ``trees``, ``dirty``, ``uncommitted``.

    The record of :func:`receipts.evaluation.e0.instrument_state` over
    :data:`INSTRUMENT_RECORD_PATHS` (HEAD, each path's git tree at HEAD or None, and the
    uncommitted changes under them, untracked files included).

    Raises:
        ValueError: git cannot read ``root``.
    """
    try:
        state = instrument_state(root, INSTRUMENT_RECORD_PATHS)
    except E0Error as exc:
        raise ValueError(f"cannot read the instrument in {root} with git: {exc}") from exc
    return {key: state[key] for key in INSTRUMENT_KEYS}


# ------------------------------------------------------------------- valid types


@dataclass(frozen=True)
class TypeCounts:
    """Held-out counts of one claim type, with ignored items left out.

    Attributes:
        claim_type: The claim type.
        gold: Items with a gold verdict.
        predicted: Items with a predicted verdict.
        correct: Gold items whose predicted verdict equals the gold one.
    """

    claim_type: str
    gold: int
    predicted: int
    correct: int

    @property
    def precision(self) -> float | None:
        """``correct / predicted``, or None without predictions."""
        return self.correct / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        """``correct / gold``, or None without gold claims."""
        return self.correct / self.gold if self.gold else None

    @property
    def status(self) -> str:
        """``valid``, or the first reason the type is not valid."""
        if not self.gold:
            return "no gold claims"
        if self.gold < GOLD_MIN:
            return f"fewer than {GOLD_MIN} gold claims"
        if not self.predicted:
            return "no predicted claims"
        low = []
        if self.correct / self.predicted < PRECISION_MIN:
            low.append(f"precision below {PRECISION_MIN}")
        if self.correct / self.gold < RECALL_MIN:
            low.append(f"recall below {RECALL_MIN}")
        return " and ".join(low) if low else "valid"

    @property
    def valid(self) -> bool:
        """At least :data:`GOLD_MIN` gold claims, a prediction, and both thresholds met."""
        return self.status == "valid"

    def as_dict(self) -> dict[str, Any]:
        """Counts, point estimates (None when undefined), ``valid``, and ``status``."""
        return {
            "gold": self.gold,
            "predicted": self.predicted,
            "correct": self.correct,
            "precision": self.precision,
            "recall": self.recall,
            "valid": self.valid,
            "status": self.status,
        }


@dataclass(frozen=True)
class ValidTypes:
    """The valid claim types of a held-out seeded evaluation (see the module docstring).

    Attributes:
        types: The valid types, sorted.
        per_type: :class:`TypeCounts` for every type in the scored items, by name.
        instrument: The evaluated instrument: ``commit``, ``paths``, ``trees``.
        sha256: SHA-256 of the evaluation file's bytes, or None when not known.
    """

    types: tuple[str, ...]
    per_type: Mapping[str, TypeCounts]
    instrument: Mapping[str, Any]
    sha256: str | None

    def as_dict(self) -> dict[str, Any]:
        """JSON form: the types, per-type counts, the rule, thresholds, and sources."""
        return {
            "types": list(self.types),
            "per_type": {name: counts.as_dict() for name, counts in self.per_type.items()},
            "rule": VALID_TYPE_RULE,
            "thresholds": {
                "gold_min": GOLD_MIN,
                "precision_min": PRECISION_MIN,
                "recall_min": RECALL_MIN,
            },
            "instrument": {
                "commit": self.instrument["commit"],
                "paths": list(self.instrument["paths"]),
                "trees": dict(self.instrument["trees"]),
            },
            "seeded_eval_sha256": self.sha256,
        }


def _evaluated_instrument(value: object) -> dict[str, Any]:
    """``commit``, ``paths``, ``trees`` of an evaluation's instrument; ValueError if malformed."""
    if not isinstance(value, Mapping):
        raise ValueError("the seeded evaluation records no instrument")
    commit, paths, trees = value.get("commit"), value.get("paths"), value.get("trees")
    if not isinstance(commit, str) or not commit:
        raise ValueError("the seeded evaluation's instrument has no commit")
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("the seeded evaluation's instrument paths are not a list of paths")
    if not isinstance(trees, Mapping) or not all(
        isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in trees.items()
    ):
        raise ValueError("the seeded evaluation's instrument trees are not path to tree ids")
    return {"commit": commit, "paths": list(paths), "trees": dict(trees)}


def valid_types(seeded_eval: Mapping[str, Any], *, sha256: str | None = None) -> ValidTypes:
    """The claim types valid for the analyses (rule in the module docstring).

    Args:
        seeded_eval: The content of ``artifacts/e0/seeded_eval.json``.
        sha256: The SHA-256 of the file's bytes, recorded as given
            (:func:`load_valid_types` computes it).

    Raises:
        ValueError: It is not the held-out split; it has no items list; an item is not
            an object, has no claim type, has a verdict outside supported,
            contradicted, and unverifiable, has an ``ignored`` other than true or
            false, or is ignored and has a gold verdict; the instrument is missing or
            malformed; or ``sha256`` is not 64 lowercase hex digits.
    """
    if sha256 is not None and not _SHA256.match(sha256):
        raise ValueError(f"{sha256!r} is not a SHA-256 digest (64 lowercase hex digits)")
    if seeded_eval.get("split") != "heldout":
        raise ValueError("the seeded evaluation is not the held-out split (split: heldout)")
    items = seeded_eval.get("items")
    if not isinstance(items, list):
        raise ValueError("the seeded evaluation has no items list")
    tallies: dict[str, list[int]] = {}
    for index, entry in enumerate(items):
        if not isinstance(entry, Mapping):
            raise ValueError(f"seeded_eval item {index} is not an object")
        ctype = entry.get("claim_type")
        if not isinstance(ctype, str) or not ctype:
            raise ValueError(f"seeded_eval item {index} has no claim_type")
        gold, pred = entry.get("gold_verdict"), entry.get("pred_verdict")
        for name, value in (("gold_verdict", gold), ("pred_verdict", pred)):
            if value is not None and (not isinstance(value, str) or value not in VERDICTS):
                raise ValueError(f"seeded_eval item {index} has an unknown {name} {value!r}")
        ignored = entry.get("ignored", False)
        if ignored is not None and not isinstance(ignored, bool):
            raise ValueError(f"seeded_eval item {index}: ignored must be true or false")
        if ignored is True:
            if gold is not None:
                raise ValueError(f"seeded_eval item {index} is ignored but has a gold verdict")
            continue
        tally = tallies.setdefault(ctype, [0, 0, 0])
        tally[0] += gold is not None
        tally[1] += pred is not None
        tally[2] += gold is not None and pred == gold
    instrument = _evaluated_instrument(seeded_eval.get("instrument"))
    per_type = {
        name: TypeCounts(name, gold=g, predicted=p, correct=c)
        for name, (g, p, c) in sorted(tallies.items())
    }
    return ValidTypes(
        types=tuple(name for name, counts in per_type.items() if counts.valid),
        per_type=per_type,
        instrument=instrument,
        sha256=sha256,
    )


def load_valid_types(path: Path) -> ValidTypes:
    """:func:`valid_types` of the evaluation file at ``path``, with its bytes' SHA-256.

    The bytes are read once, so the digest is the digest of the content scored.

    Raises:
        ValueError: The file is not a JSON object, or :func:`valid_types` refuses it.
        OSError: The file cannot be read.
    """
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return valid_types(data, sha256=hashlib.sha256(raw).hexdigest())
