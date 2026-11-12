"""Bank a study's runs into the artifacts the gates and analyses read.

    python tools/bank_study.py smoke                 # artifacts/bench/smoke_runs.json (G6)
    python tools/bank_study.py pilot                 # artifacts/studies/pilot/summary.json
    python tools/bank_study.py e1 [--allow-dirty]    # artifacts/e1/runs.jsonl (G7, G8)
    python tools/bank_study.py e4 [--allow-dirty]    # artifacts/e4/runs.jsonl (G9)
    python tools/bank_study.py e1 --check            # compare, write nothing (G7; e4: G9)

smoke and pilot read the banked ``artifacts/studies/<study>/runs/*/run.json`` files.

smoke also ties every banked run to the smoke plan (``artifacts/studies/smoke/plan.json``,
DECISIONS D71) and refuses (exit 2, nothing written) a run that was not made as planned
(:func:`receipts.study.plan.run_record_problems`): a run the plan does not hold, a run a
plan amendment replaced (an excluded run stays excluded), a run that does not record
its planned task, arm, and run spec, or a run an amendment added that does not record
the amendment and a model server meeting its requirement. Each row of
``artifacts/bench/smoke_runs.json`` is then a run gate G6 can tie to its plan. The
smoke failure log is banked as e1's and e4's are (below), with its summary in
``smoke_runs.json`` (``failures``), so the attempts that excluded a run stay on record.

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

``--check`` (e1 and e4; DECISIONS D57) re-derives the rows exactly as banking does, with
the same refusals and from committed code only, writes nothing, and compares them with
the committed ``artifacts/<study>/runs.jsonl``: the rows must be those of exactly the
banked runs, each once, with every field equal as JSON, except the banking commit in
each row's instrument record (``instrument.commit``), which says where the rows were
banked and not what they hold. Exit 0 when they are the same rows, 1 when they differ
(each difference on stderr), 2 when the rows cannot be re-derived. Gates G7 and G9 run
it in the fresh clone, because claims and verdicts need the instrument.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import receipts
from receipts.bench.hashing import tree_sha256
from receipts.evaluation.e0 import E0Error, uncommitted
from receipts.study import aggregate, rescore

ROOT = Path(__file__).resolve().parents[1]
STUDIES: tuple[str, ...] = ("smoke", "pilot", "e1", "e4")
#: The plan every banked smoke run must be a run of (DECISIONS D71).
SMOKE_PLAN = "artifacts/studies/smoke/plan.json"
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


def _listed(items: Sequence[str]) -> str:
    """The first five of ``items``, comma separated, with ``...`` when there are more."""
    return ", ".join(items[:5]) + (", ..." if len(items) > 5 else "")


def smoke_problems(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every way the banked smoke runs ``records`` were not made as the smoke plan plans
    them (:func:`receipts.study.plan.run_record_problems`), each after its run id; a
    missing plan, or one whose amendments do not hold, is a problem too."""
    # Imported here, not with the module: these checks never compute an e1 or e4 row, so
    # the plan module stays out of the code that banks them (BANKING_CODE in
    # tools/analyze.py lists what a row depends on).
    from receipts.study.plan import check_amendments, load_plan, run_record_problems

    path = ROOT / SMOKE_PLAN
    if not path.is_file():
        return [f"{SMOKE_PLAN} is missing, so no smoke run can be tied to its plan"]
    try:
        plan = load_plan(path)
        check_amendments(plan)
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{SMOKE_PLAN}: {exc}"]
    return [
        f"{record.get('run_id')}: {problem}"
        for record in records
        for problem in run_record_problems(plan, record)
    ]


@dataclass(frozen=True)
class Banking:
    """What banking one study derives before it writes anything.

    Attributes:
        rows: One row per banked run, sorted by run id.
        instrument: The checkout's instrument record (``rescore.instrument_record``).
        dirty: The uncommitted paths of the instrument and the banking code.
        valid: The held-out evaluation's valid types, or None without one.
        runs_dir: The directory that holds the banked runs.
    """

    rows: list[dict[str, Any]]
    instrument: dict[str, Any]
    dirty: list[str]
    valid: rescore.ValidTypes | None
    runs_dir: Path


def derive_rows(study: str, *, allow_dirty: bool, dirty_hint: str) -> Banking:
    """Rescore every banked run of ``study`` (``e1`` or ``e4``) and build its rows.

    Raises:
        RefusalError: ``receipts`` is imported from another tree than this checkout's
            ``src/``; the instrument or the banking code has uncommitted changes and
            ``allow_dirty`` is false (the message ends with ``dirty_hint``); the
            held-out evaluation is malformed; or a run cannot be rescored.
    """
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
        raise RefusalError(
            f"uncommitted changes in the instrument or the banking code ({_listed(dirty)}); "
            + dirty_hint
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
    return Banking(rows, instrument, dirty, valid, runs_dir)


def comparable(row: Mapping[str, Any]) -> dict[str, str]:
    """Each field of a row as canonical JSON, so ``1``, ``1.0``, and ``true`` differ.

    The instrument record's fields count one by one, and its ``commit`` is left out: it
    says where the rows were banked, not what they hold (the gates check separately
    that it holds the evaluated instrument).
    """
    out: dict[str, str] = {}
    for key, value in row.items():
        if key == "instrument" and isinstance(value, Mapping):
            # Kept apart from the row's own keys with a prefix that no row key can carry
            # (a key may contain a dot, never a NUL), so a top-level key spelled like a
            # flattened field cannot overwrite it in the comparison.
            out.update(
                (f"instrument\0{name}", json.dumps(item, sort_keys=True))
                for name, item in value.items()
                if name != "commit"
            )
        else:
            out[key] = json.dumps(value, sort_keys=True)
    return out


def row_problems(path: Path, fresh: Sequence[Mapping[str, Any]], runs_dir: Path) -> list[str]:
    """Every way the committed rows file ``path`` differs from the ``fresh`` rows that
    banking builds now from the runs under ``runs_dir``: the file is missing; a line is
    not JSON or not a row with a run id; a run id repeats; a banked run has no row; a
    row has no banked run; or a row's fields differ from its fresh row's
    (:func:`comparable`)."""
    name = rel(path)
    if not path.is_file():
        return [f"{name} is missing, so there are no committed rows to compare"]
    problems: list[str] = []
    committed: dict[str, Mapping[str, Any]] = {}
    repeated: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{name}:{number} is not JSON ({exc.msg})")
            continue
        run_id = row.get("run_id") if isinstance(row, dict) else None
        if not isinstance(run_id, str):
            problems.append(f"{name}:{number} is not a row with a run_id")
            continue
        if run_id in committed:
            repeated.add(run_id)
        committed[run_id] = row
    banked = {str(row["run_id"]): row for row in fresh}
    if repeated:
        problems.append(f"{len(repeated)} run id(s) repeat in {name}: {_listed(sorted(repeated))}")
    unrowed = sorted(set(banked) - set(committed))
    if unrowed:
        problems.append(f"{len(unrowed)} banked run(s) have no row in {name}: {_listed(unrowed)}")
    unbanked = sorted(set(committed) - set(banked))
    if unbanked:
        problems.append(
            f"{len(unbanked)} row(s) have no banked run under {rel(runs_dir)}: " + _listed(unbanked)
        )
    differing: dict[str, list[str]] = {}
    for run_id in sorted(set(committed) & set(banked)):
        mine, theirs = comparable(committed[run_id]), comparable(banked[run_id])
        fields = sorted(k for k in mine.keys() | theirs.keys() if mine.get(k) != theirs.get(k))
        if fields:
            differing[run_id] = fields
    if differing:
        named = sorted(
            {field.replace("\0", ".") for fields in differing.values() for field in fields}
        )
        problems.append(
            f"{len(differing)} row(s) differ from the rows banking writes now in "
            f"{', '.join(named)}: {_listed(sorted(differing))}"
        )
        if "instrument.trees" in named:
            problems.append(
                "the instrument in this checkout is not the one those rows were banked with, "
                "so this checkout does not re-derive them"
            )
    return problems


def check_rescored(study: str) -> int:
    """Re-derive the rows of ``study`` (``e1`` or ``e4``) and compare them with the
    committed rows file, writing nothing; return 0 when they are the same rows, else 1."""
    banking = derive_rows(
        study,
        allow_dirty=False,
        dirty_hint="commit them, since a check re-derives the rows from committed code only",
    )
    path = ROOT / "artifacts" / study / "runs.jsonl"
    problems = row_problems(path, banking.rows, banking.runs_dir)
    for problem in problems:
        print(f"bank_study {study} --check: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"{study}: the {len(banking.rows)} row(s) of {rel(path)} are the rows banking writes "
        f"now from the banked runs under {rel(banking.runs_dir)} (re-extracted and "
        "re-verified; only the banking commit may differ)"
    )
    return 0


def bank_rescored(study: str, *, allow_dirty: bool) -> int:
    """Rescore and bank every run of ``study`` (``e1`` or ``e4``); return the exit code."""
    banking = derive_rows(
        study,
        allow_dirty=allow_dirty,
        dirty_hint="commit them, or bank exploratory rows with --allow-dirty",
    )
    rows, instrument, dirty = banking.rows, banking.instrument, banking.dirty
    valid, runs_dir = banking.valid, banking.runs_dir
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="e1 and e4: re-derive the rows from the banked runs and compare them with the "
        "committed rows file, writing nothing (exit 1 when they differ)",
    )
    args = parser.parse_args(argv)
    if args.allow_dirty and args.study not in aggregate.ROW_STUDIES:
        parser.error("--allow-dirty applies to e1 and e4 only")
    if args.check and args.study not in aggregate.ROW_STUDIES:
        parser.error("--check applies to e1 and e4 only")
    if args.check and args.allow_dirty:
        parser.error("--check re-derives the rows from committed code only (no --allow-dirty)")
    if args.study in aggregate.ROW_STUDIES:
        try:
            if args.check:
                return check_rescored(args.study)
            return bank_rescored(args.study, allow_dirty=args.allow_dirty)
        except RefusalError as exc:
            print(f"bank_study {args.study}: refused: {exc}", file=sys.stderr)
            return 2
    runs = ROOT / "artifacts" / "studies" / args.study / "runs"
    records = aggregate.load_records(runs)
    prov = provenance(args.study)
    if args.study == "smoke":
        problems = smoke_problems(records)
        try:
            failures = None if problems else banked_failures("smoke")
        except RefusalError as exc:
            problems = [str(exc)]
        if problems:
            for problem in problems:
                print(f"bank_study smoke: refused: {problem}", file=sys.stderr)
            return 2
        if failures is not None:
            target, text, _ = failures
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        # Claim-type counts (G5) come from blind labels, not the extractor (D34, D43):
        # tools/e0.py counts them from labeler subagents' labels of each smoke report.
        artifact = aggregate.smoke_runs_artifact(records, prov)
        artifact["failures"] = None if failures is None else failures[2]
        write_json(ROOT / "artifacts/bench/smoke_runs.json", artifact)
    else:
        write_json(
            ROOT / "artifacts/studies/pilot/summary.json",
            aggregate.pilot_summary_artifact(records, prov),
        )
    print(f"{args.study}: banked {len(records)} run(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
