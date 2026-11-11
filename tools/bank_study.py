"""Bank a study's runs into the artifacts the gates and analyses read.

    python tools/bank_study.py smoke                 # artifacts/bench/smoke_runs.json (G6)
    python tools/bank_study.py pilot                 # artifacts/studies/pilot/summary.json
    python tools/bank_study.py e1 [--allow-dirty]    # artifacts/e1/runs.jsonl (G7, G8)
    python tools/bank_study.py e4 [--allow-dirty]    # artifacts/e4/runs.jsonl (G9)

smoke and pilot read the banked ``artifacts/studies/<study>/runs/*/run.json`` files.

e1 and e4 follow DECISIONS D42 item 1: every banked run is rescored
(:func:`receipts.study.rescore.rescore_run`): its final report is re-extracted and
re-verified against its banked ledger with the task's requirements, using the
instrument in this checkout, and the rows (:mod:`receipts.study.aggregate`) take their
outcomes from the rescoring; the verdicts ``run.json`` banked at run time are kept as a
diagnostic (``runtime_agrees``). The banking refuses (exit 2, nothing written) when:

- ``receipts`` is imported from another tree than this checkout's ``src/`` (a code
  snapshot, for example), so the recorded instrument would not be the code that ran;
- the instrument (``rescore.instrument_record``) or the banking code
  (:data:`BANKING_CODE`) has uncommitted changes, unless ``--allow-dirty``, which marks
  every row ``instrument_dirty: true`` and so makes the rows exploratory;
- a run cannot be rescored as banked (a broken hash chain, a report other than the
  ledger's, a ledger of another run), or its task's files differ from the ones the run
  recorded (``provenance.task_tree_sha256``), because the requirement texts the
  verifier maps claims to come from those files; ``--allow-dirty`` does not lift this;
- the held-out evaluation exists but is malformed, or the failure log is malformed.

``any_contradicted`` counts the valid types of ``artifacts/e0/seeded_eval.json`` when it
is the held-out evaluation, and is null otherwise. ``runs/<study>/failures.jsonl`` (git
ignored), when present, is banked as ``artifacts/studies/<study>/failures.jsonl`` with
every key but ``trace``; entries banked earlier stay, so a reset log never drops a
logged failure. ``artifacts/<study>/runs.provenance.json`` records the provenance (git
SHA, command, time, plan SHA-256, the instrument record, and the SHA-256 of the
seeded evaluation used for ``any_contradicted``) and what was banked.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import receipts
from receipts.bench.hashing import tree_sha256
from receipts.evaluation.e0 import E0Error, uncommitted
from receipts.study import aggregate, rescore

ROOT = Path(__file__).resolve().parents[1]
STUDIES: tuple[str, ...] = ("smoke", "pilot", "e1", "e4")
#: The held-out G5 evaluation whose valid types ``any_contradicted`` counts.
SEEDED_EVAL = "artifacts/e0/seeded_eval.json"
#: Code that turns banked runs into rows, besides the instrument: it must be committed
#: too (``src/`` holds the instrument, the rescoring, and the row contract).
BANKING_CODE: tuple[str, ...] = ("src", "tools/bank_study.py")
#: The keys of a failure log entry the banked copy leaves out (the traceback).
DROPPED_FAILURE_KEYS = frozenset({"trace"})


class RefusalError(Exception):
    """The banking cannot proceed; nothing has been written."""


def provenance(study: str) -> dict[str, str]:
    """Provenance for an artifact derived from ``study``'s banked runs."""
    sha = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    plan = ROOT / "artifacts" / "studies" / study / "plan.json"
    return {
        "git_sha": sha,
        "command": " ".join([sys.executable, *sys.argv]),
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else "",
        "study": study,
    }


def write_json(path: Path, data: object) -> None:
    """Write a JSON artifact with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    """``path`` relative to :data:`ROOT`, POSIX style."""
    return path.relative_to(ROOT).as_posix()


def imported_src() -> Path:
    """The ``src`` directory the running ``receipts`` package was imported from."""
    return Path(receipts.__file__).resolve().parents[1]


def seeded_valid_types() -> rescore.ValidTypes | None:
    """The valid types of the held-out evaluation, or None when there is none."""
    path = ROOT / SEEDED_EVAL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_bytes())
        if isinstance(data, dict) and data.get("split") != "heldout":
            return None
        return rescore.load_valid_types(path)
    except (ValueError, OSError) as exc:
        raise RefusalError(f"{SEEDED_EVAL}: {exc}") from exc


def rescored_runs(runs_dir: Path) -> list[aggregate.RunPair]:
    """Every banked run under ``runs_dir`` with its rescoring, sorted by run id.

    Raises:
        RefusalError: A run cannot be rescored, or its task files changed since it ran.
    """
    pairs: list[aggregate.RunPair] = []
    requirements: dict[str, dict[str, str]] = {}
    trees: dict[str, str] = {}
    for run_dir in sorted(p.parent for p in runs_dir.glob("*/run.json")):
        try:
            record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("run.json is not a JSON object")
            task_id = record.get("task_id")
            if not isinstance(task_id, str):
                raise ValueError("run.json has no task_id")
            if task_id not in requirements:
                requirements[task_id] = rescore.task_requirements(ROOT, task_id)
                trees[task_id] = tree_sha256(ROOT / "bench" / "tasks" / task_id)
            prov = record.get("provenance")
            recorded = prov.get("task_tree_sha256") if isinstance(prov, dict) else None
            if recorded is not None and recorded != trees[task_id]:
                raise ValueError(
                    f"the task files of {task_id} differ from the ones the run recorded "
                    f"(task_tree_sha256 {str(recorded)[:12]}, now {trees[task_id][:12]}); "
                    "the verifier would map claims to other requirement texts"
                )
            pairs.append((record, rescore.rescore_run(run_dir, requirements[task_id])))
        except (ValueError, OSError) as exc:
            raise RefusalError(f"{run_dir.name}: {exc}") from exc
    return pairs


def failure_entries(path: Path) -> list[dict[str, Any]]:
    """The entries of a failure log, without :data:`DROPPED_FAILURE_KEYS`.

    Raises:
        RefusalError: A line is not a JSON object with a run id.
    """
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RefusalError(f"{rel(path)}:{number} is not JSON ({exc.msg})") from exc
        run_id = entry.get("run_id") if isinstance(entry, dict) else None
        if not isinstance(run_id, str) or not run_id:
            raise RefusalError(f"{rel(path)}:{number} is not a failure entry with a run_id")
        entries.append({k: v for k, v in entry.items() if k not in DROPPED_FAILURE_KEYS})
    return entries


def banked_failures(study: str) -> tuple[Path, str, dict[str, Any]] | None:
    """The banked failure log to write: ``(path, text, summary)``, or None without a log.

    The result holds every entry banked before, then each logged entry it does not hold
    yet (counted as a multiset, so a failure logged twice is banked twice).
    """
    source = ROOT / "runs" / study / "failures.jsonl"
    if not source.is_file():
        return None
    target = ROOT / "artifacts" / "studies" / study / "failures.jsonl"
    earlier = failure_entries(target) if target.is_file() else []
    remaining = Counter(json.dumps(e, sort_keys=True) for e in earlier)
    merged = list(earlier)
    for entry in failure_entries(source):
        key = json.dumps(entry, sort_keys=True)
        if remaining[key]:
            remaining[key] -= 1
        else:
            merged.append(entry)
    text = "".join(json.dumps(e, sort_keys=True) + "\n" for e in merged)
    summary = {
        "source": rel(source),
        "banked": rel(target),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "entries": len(merged),
        "added": len(merged) - len(earlier),
    }
    return target, text, summary


def bank_rescored(study: str, *, allow_dirty: bool) -> int:
    """Rescore and bank every run of ``study`` (``e1`` or ``e4``); return the exit code."""
    if imported_src().resolve() != (ROOT / "src").resolve():
        raise RefusalError(
            f"receipts is imported from {imported_src()}, not from {ROOT / 'src'}: the "
            "instrument record would not describe the code that rescores"
        )
    try:
        instrument = rescore.instrument_record(ROOT)
        code = uncommitted(ROOT, *BANKING_CODE)
    except (ValueError, E0Error) as exc:
        raise RefusalError(str(exc)) from exc
    dirty = sorted({*instrument["uncommitted"], *code})
    if dirty and not allow_dirty:
        listed = ", ".join(dirty[:5]) + (", ..." if len(dirty) > 5 else "")
        raise RefusalError(
            f"uncommitted changes in the instrument or the banking code ({listed}); commit "
            "them, or bank exploratory rows with --allow-dirty"
        )
    valid = seeded_valid_types()
    runs_dir = ROOT / "artifacts" / "studies" / study / "runs"
    pairs = rescored_runs(runs_dir)
    make_rows = aggregate.e1_rows if study == "e1" else aggregate.e4_rows
    try:
        rows = make_rows(
            pairs, instrument, None if valid is None else valid.types, instrument_dirty=bool(dirty)
        )
    except ValueError as exc:
        raise RefusalError(str(exc)) from exc
    failures = banked_failures(study)
    rows_path = ROOT / "artifacts" / study / "runs.jsonl"
    aggregate.write_jsonl(rows_path, rows)
    if failures is not None:
        target, text, _ = failures
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    prov: dict[str, Any] = {
        **provenance(study),
        "instrument": instrument,
        "seeded_eval": None if valid is None else SEEDED_EVAL,
        "seeded_eval_sha256": None if valid is None else valid.sha256,
    }
    disagree = [str(row["run_id"]) for row in rows if not row["runtime_agrees"]]
    write_json(
        ROOT / "artifacts" / study / "runs.provenance.json",
        {
            "schema": "receipts.study.bank/1",
            "study": study,
            "rows": rel(rows_path),
            "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
            "runs_dir": rel(runs_dir),
            "method": "outcomes re-extracted and re-verified at banking from each run's "
            "final report and banked ledger with the task's requirements (DECISIONS D42); "
            "run-time verdicts are diagnostics (runtime_agrees)",
            "runtime_disagreements": disagree,
            "valid_types": None if valid is None else list(valid.types),
            "failures": None if failures is None else failures[2],
            "allow_dirty": allow_dirty,
            "instrument_dirty": bool(dirty),
            "uncommitted": dirty,
            "provenance": prov,
        },
    )
    note = "; exploratory: uncommitted code (instrument_dirty)" if dirty else ""
    print(
        f"{study}: banked {len(rows)} run(s), rescored; {len(disagree)} differ from the "
        f"run-time verdicts{note}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Derive the gate artifacts for one study."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("study", choices=STUDIES)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="e1 and e4: bank even though the instrument or the banking code has "
        "uncommitted changes; the rows are then marked instrument_dirty (exploratory)",
    )
    args = parser.parse_args(argv)
    if args.allow_dirty and args.study not in aggregate.ROW_STUDIES:
        parser.error("--allow-dirty applies to e1 and e4 only")
    if args.study in aggregate.ROW_STUDIES:
        try:
            return bank_rescored(args.study, allow_dirty=args.allow_dirty)
        except RefusalError as exc:
            print(f"bank_study {args.study}: refused: {exc}", file=sys.stderr)
            return 2
    runs = ROOT / "artifacts" / "studies" / args.study / "runs"
    records = aggregate.load_records(runs)
    prov = provenance(args.study)
    if args.study == "smoke":
        # Claim-type counts (G5) come from blind labels, not the extractor (D34, D43):
        # tools/e0.py counts them from labeler subagents' labels of each smoke report.
        write_json(
            ROOT / "artifacts/bench/smoke_runs.json", aggregate.smoke_runs_artifact(records, prov)
        )
    else:
        write_json(
            ROOT / "artifacts/studies/pilot/summary.json",
            aggregate.pilot_summary_artifact(records, prov),
        )
    print(f"{args.study}: banked {len(records)} run(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
