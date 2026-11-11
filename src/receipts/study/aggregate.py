"""Turn banked runs into the artifacts the ship gates and analyses read (docs/PLAN.md).

- :func:`smoke_runs_artifact`: ``artifacts/bench/smoke_runs.json`` (G6): one row per
  real, non-synthetic agent run per task.
- :func:`claim_type_counts_artifact`: ``artifacts/e0/claim_type_counts.json`` (G5): how
  often each claim type appears in real smoke-run reports, with the source run ids.
- :func:`e1_rows` and :func:`e4_rows`: ``artifacts/e1/runs.jsonl`` (G7, G8) and
  ``artifacts/e4/runs.jsonl`` (G9): one row per banked run, built by :func:`run_row` from
  its ``run.json`` and its rescoring (:class:`receipts.study.rescore.Rescored`).
- :func:`pilot_summary_artifact`: per-arm run time, turns, tokens, and stop reasons of a
  pilot (planning input for study sizes; never pooled with confirmatory data).

The smoke, claim-count, and pilot artifacts read only banked ``run.json`` files.

Row contract (DECISIONS D42 item 1). Every outcome comes from the rescoring, never from
the verdicts ``run.json`` banked at run time:

- From ``run.json``: ``run_id``, ``config_id``, ``model``, ``model_family`` (its
  ``family``), ``task_id``, ``conditions``, ``seed``, ``synthetic`` (its flag, False when
  absent), and ``mitigation`` (``none`` in every E1 row; an E1 record with another
  mitigation is refused).
- From the rescoring: ``included`` (the final report is non-empty after stripping white
  space), ``completed`` (stop reason ``finished`` and included), ``stop_reason``,
  ``turns``, ``report_sha256`` (SHA-256 of the UTF-8 text of the report as the ledger
  stores it, a lone surrogate as U+FFFD; ``run.json``'s report must equal it after
  :func:`receipts.ledger.events.stored_text`), ``false_success``,
  ``success_reported``, ``ground_truth_success``, ``omissions``, ``claims`` (each with
  ``claim_id``, ``claim_type``, ``text``, ``verdict``, ``evidence``), ``runtime_agrees``
  (diagnostic), and ``any_contradicted``: a contradicted claim of a valid type when the
  valid types are given (:func:`receipts.study.rescore.valid_types` of the held-out
  evaluation), else None. The analyses never read ``any_contradicted``.
- From the run's provenance: ``run_code`` (:func:`run_code`) and ``task_tree_sha256``
  (None when absent).
- From the banking checkout: ``instrument`` (the record of
  :func:`receipts.study.rescore.instrument_record`, the same in every row) and
  ``instrument_dirty`` (true when that record is dirty or the caller says the rows came
  from uncommitted code; such rows are exploratory).
- E4 rows also carry ``input_tokens``, ``output_tokens``, ``wall_s``, ``model_wall_s``,
  ``hook_checks``, and ``drafts`` as ``run.json`` has them.
"""

from __future__ import annotations

import copy
import json
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeAlias

from receipts.ledger.events import sha256_text, stored_text
from receipts.study.rescore import INSTRUMENT_KEYS, Rescored
from receipts.study.spec import MITIGATIONS

#: The studies whose rows come from rescored runs.
ROW_STUDIES: tuple[str, ...] = ("e1", "e4")
#: The ``run.json`` fields only E4 rows carry, with their types.
E4_FIELDS: tuple[tuple[str, type], ...] = (
    ("input_tokens", int),
    ("output_tokens", int),
    ("wall_s", float),
    ("model_wall_s", float),
    ("hook_checks", list),
    ("drafts", list),
)
#: A banked run: its ``run.json`` record and its rescoring.
RunPair: TypeAlias = tuple[Mapping[str, Any], Rescored]


def load_records(runs_dir: Path) -> list[dict[str, Any]]:
    """Every banked ``run.json`` under ``runs_dir``, sorted by run id."""
    records = [json.loads(path.read_text(encoding="utf-8")) for path in runs_dir.glob("*/run.json")]
    return sorted(records, key=lambda r: str(r["run_id"]))


def smoke_runs_artifact(
    records: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """The G6 smoke-run artifact: these are real model runs, so ``synthetic`` is False."""
    runs = [
        {
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "agent": f"minimal-agent/{r['model']}",
            "config_id": r["config_id"],
            "stop_reason": r["stop_reason"],
            "turns": r["turns"],
            "synthetic": False,
        }
        for r in records
    ]
    return {"schema": "receipts.bench.smoke_runs/1", "runs": runs, "provenance": dict(provenance)}


def claim_type_counts_artifact(
    records: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """Claim-type frequencies over the real reports of ``records`` (G5 top five)."""
    counts: Counter[str] = Counter()
    sources = []
    for record in records:
        claims = record.get("claims", [])
        if claims:
            sources.append(str(record["run_id"]))
        counts.update(str(c["type"]) for c in claims)
    return {
        "schema": "receipts.e0.claim_type_counts/1",
        "source": "smoke-run final reports, pattern extractor",
        "counts": dict(sorted(counts.items())),
        "source_runs": sources,
        "provenance": dict(provenance),
    }


def _optional_text(provenance: Mapping[str, Any], key: str) -> str | None:
    """``provenance[key]`` as a string, or None when absent or null."""
    value = provenance.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"provenance.{key} must be a string or absent, not {value!r}")
    return value


def _under_src(entry: str) -> bool:
    """True for a ``git status --porcelain`` path entry (a path, a quoted path, or a
    rename ``old -> new``) that names a path under ``src/``."""
    return any(part.strip().strip('"').startswith("src/") for part in entry.split(" -> "))


def run_code(provenance: object) -> dict[str, Any]:
    """The code a run ran, from its ``run.json`` provenance (as ``tools/run_study.py``
    records it).

    Returns:
        ``git_sha``, ``code`` (``snapshot`` or ``working tree``), and ``snapshot_of``,
        each None when absent, and ``uncommitted_src``: the entries of
        ``uncommitted_at_start`` under ``src/`` (an empty list when there are none),
        or None when the provenance has no such field.

    Raises:
        ValueError: The provenance is not an object (or absent), or a field has the
            wrong type.
    """
    if provenance is not None and not isinstance(provenance, Mapping):
        raise ValueError("provenance must be an object")
    prov: Mapping[str, Any] = provenance if isinstance(provenance, Mapping) else {}
    uncommitted = prov.get("uncommitted_at_start")
    if uncommitted is not None and (
        not isinstance(uncommitted, list) or not all(isinstance(p, str) for p in uncommitted)
    ):
        raise ValueError("provenance.uncommitted_at_start must be a list of paths")
    return {
        "git_sha": _optional_text(prov, "git_sha"),
        "code": _optional_text(prov, "code"),
        "snapshot_of": _optional_text(prov, "snapshot_of"),
        "uncommitted_src": None
        if uncommitted is None
        else [p for p in uncommitted if _under_src(p)],
    }


def _field(record: Mapping[str, Any], name: str, kind: type) -> Any:
    """``record[name]``, refusing a missing field or one of another type (bools are not
    numbers; an int is a float)."""
    value = record.get(name)
    ok = isinstance(value, kind) or (kind is float and isinstance(value, int))
    if not ok or (kind in (int, float) and isinstance(value, bool)):
        raise ValueError(
            f"run {record.get('run_id')!r}: run.json field {name} must be a {kind.__name__}"
        )
    return value


def _check_instrument(instrument: Mapping[str, Any]) -> None:
    """Refuse a malformed instrument record (:data:`receipts.study.rescore.INSTRUMENT_KEYS`)."""
    kinds: dict[str, type] = {
        "commit": str,
        "paths": list,
        "trees": dict,
        "dirty": bool,
        "uncommitted": list,
    }
    missing = [k for k in INSTRUMENT_KEYS if not isinstance(instrument.get(k), kinds[k])]
    if missing or not instrument.get("commit"):
        raise ValueError(f"the instrument record is malformed ({', '.join(missing) or 'commit'})")


def run_row(
    record: Mapping[str, Any],
    rescored: Rescored,
    *,
    study: str,
    instrument: Mapping[str, Any],
    instrument_dirty: bool = False,
    valid_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """The row of one banked run (the row contract in the module docstring).

    Args:
        record: The run's ``run.json``.
        rescored: Its rescoring (:func:`receipts.study.rescore.rescore_run`).
        study: ``e1`` or ``e4``.
        instrument: The banking checkout's instrument record.
        instrument_dirty: The rows came from code with uncommitted changes (banking with
            ``--allow-dirty``); a dirty ``instrument`` marks the row either way.
        valid_types: The valid claim types for ``any_contradicted`` (None: unknown).

    Raises:
        ValueError: ``study`` is not e1 or e4; the rescoring is of another run or another
            report; a field is missing or mistyped; the mitigation does not belong to
            the study; or the instrument record is malformed.
    """
    if study not in ROW_STUDIES:
        raise ValueError(f"no row contract for study {study!r}")
    _check_instrument(instrument)
    run_id = _field(record, "run_id", str)
    if rescored.run_id != run_id:
        raise ValueError(f"run {run_id!r}: paired with the rescoring of run {rescored.run_id!r}")
    report = record.get("report")
    if not isinstance(report, str) or stored_text(report) != rescored.report:
        raise ValueError(f"run {run_id!r}: run.json's report is not the rescored report")
    mitigation = record.get("mitigation", "none")
    if study == "e1" and mitigation != "none":
        raise ValueError(f"run {run_id!r}: an E1 run has mitigation {mitigation!r}, not 'none'")
    if mitigation not in MITIGATIONS:
        raise ValueError(f"run {run_id!r}: unknown mitigation {mitigation!r}")
    provenance = record.get("provenance")
    prov: Mapping[str, Any] = provenance if isinstance(provenance, Mapping) else {}
    try:
        code = run_code(provenance)
        task_tree = _optional_text(prov, "task_tree_sha256")
    except ValueError as exc:
        raise ValueError(f"run {run_id!r}: {exc}") from exc
    claims = copy.deepcopy(list(rescored.claims))
    included = bool(rescored.report.strip())
    valid = None if valid_types is None else set(valid_types)
    row: dict[str, Any] = {
        "run_id": run_id,
        "config_id": _field(record, "config_id", str),
        "model": _field(record, "model", str),
        "model_family": _field(record, "family", str),
        "task_id": _field(record, "task_id", str),
        "conditions": dict(_field(record, "conditions", dict)),
        "seed": _field(record, "seed", int),
        "synthetic": bool(record.get("synthetic", False)),
        "mitigation": mitigation,
        "included": included,
        "completed": rescored.stop_reason == "finished" and included,
        "stop_reason": rescored.stop_reason,
        "turns": rescored.turns,
        "report_sha256": sha256_text(rescored.report),
        "false_success": rescored.false_success,
        "success_reported": rescored.success_reported,
        "ground_truth_success": rescored.ground_truth_success,
        "omissions": rescored.omissions,
        "claims": claims,
        "any_contradicted": None
        if valid is None
        else any(c["verdict"] == "contradicted" and c["claim_type"] in valid for c in claims),
        "run_code": code,
        "task_tree_sha256": task_tree,
        "instrument": copy.deepcopy(dict(instrument)),
        "instrument_dirty": bool(instrument_dirty) or instrument["dirty"],
        "runtime_agrees": rescored.runtime_agrees,
    }
    if study == "e4":
        for name, kind in E4_FIELDS:
            value = _field(record, name, kind)
            row[name] = float(value) if kind is float else copy.deepcopy(value)
    return row


def _rows(
    study: str,
    runs: Iterable[RunPair],
    instrument: Mapping[str, Any],
    valid_types: Iterable[str] | None,
    instrument_dirty: bool,
) -> list[dict[str, Any]]:
    valid = None if valid_types is None else sorted(set(valid_types))
    rows = [
        run_row(
            record,
            rescored,
            study=study,
            instrument=instrument,
            instrument_dirty=instrument_dirty,
            valid_types=valid,
        )
        for record, rescored in runs
    ]
    seen: Counter[str] = Counter(str(row["run_id"]) for row in rows)
    repeated = sorted(run_id for run_id, n in seen.items() if n > 1)
    if repeated:
        raise ValueError(f"a run id repeats: {', '.join(repeated)}")
    return rows


def e1_rows(
    runs: Iterable[RunPair],
    instrument: Mapping[str, Any],
    valid_types: Iterable[str] | None = None,
    *,
    instrument_dirty: bool = False,
) -> list[dict[str, Any]]:
    """The rows of ``artifacts/e1/runs.jsonl``, in the order of ``runs``.

    Args:
        runs: ``(run.json record, rescoring)`` pairs, one per banked E1 run.
        instrument: The banking checkout's instrument record.
        valid_types: The valid claim types for ``any_contradicted`` (None: unknown).
        instrument_dirty: The rows came from code with uncommitted changes.

    Raises:
        ValueError: :func:`run_row` refuses a run, or a run id repeats.
    """
    return _rows("e1", runs, instrument, valid_types, instrument_dirty)


def e4_rows(
    runs: Iterable[RunPair],
    instrument: Mapping[str, Any],
    valid_types: Iterable[str] | None = None,
    *,
    instrument_dirty: bool = False,
) -> list[dict[str, Any]]:
    """The rows of ``artifacts/e4/runs.jsonl``: E1's contract plus the E4 fields.

    Arguments and errors as :func:`e1_rows`.
    """
    return _rows("e4", runs, instrument, valid_types, instrument_dirty)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write rows as JSONL with sorted keys (stable diffs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _spread(values: Sequence[float]) -> dict[str, float]:
    """Median, mean, maximum, and total of ``values`` (zeros when empty)."""
    if not values:
        return {"median": 0.0, "mean": 0.0, "max": 0.0, "total": 0.0}
    return {
        "median": round(statistics.median(values), 3),
        "mean": round(statistics.fmean(values), 3),
        "max": round(max(values), 3),
        "total": round(sum(values), 3),
    }


def pilot_summary_artifact(
    records: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """Per-arm costs and outcomes of a pilot, for sizing studies against compute.

    ``reported`` counts runs that ended with a non-empty report (the E1 inclusion rule);
    times are wall-clock seconds measured on a CPU that other processes may share.
    """
    arms: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        arms.setdefault(str(record["config_id"]), []).append(record)
    summary = {}
    for config_id, rows in sorted(arms.items()):
        summary[config_id] = {
            "model": str(rows[0]["model"]),
            "n_runs": len(rows),
            "reported": sum(bool(str(r.get("report", "")).strip()) for r in rows),
            "stop_reasons": dict(sorted(Counter(str(r["stop_reason"]) for r in rows).items())),
            "false_success": sum(bool(r["false_success"]) for r in rows),
            "claims": sum(len(r.get("claims", [])) for r in rows),
            "turns": _spread([float(r["turns"]) for r in rows]),
            "wall_s": _spread([float(r["wall_s"]) for r in rows]),
            "model_wall_s": _spread([float(r["model_wall_s"]) for r in rows]),
            "input_tokens": sum(int(r["input_tokens"]) for r in rows),
            "output_tokens": sum(int(r["output_tokens"]) for r in rows),
        }
    return {
        "schema": "receipts.study.pilot_summary/1",
        "note": "Pilot runs: planning input only, never pooled with confirmatory data. "
        "Wall times come from a shared 4-core CPU.",
        "arms": summary,
        "provenance": dict(provenance),
    }
