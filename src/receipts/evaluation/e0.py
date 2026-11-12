"""E0 tooling (gate G5): material for blind subagents, checks of their work, and scoring.

This module is the logic of ``tools/e0.py``. It prepares what blind subagents
(labelers, writers, and adjudicators) work from, checks what they produce, and scores
the instrument (the pattern extractor plus the verifier, DECISIONS D31) on the result.
It never runs a subagent, never calls a model, and needs no network. The steps, in
order (docs/E0_PROTOCOL.md, "Files and commands"):

1. :func:`write_label_packets` and :func:`check_label_files`: one packet per real smoke
   run (:func:`real_smoke_runs`) for blind labelers, who list every claim in its final
   report, and the check of what a labeler produced.
2. :func:`blind_counts_artifact`: the claim-type counts gate G5 recomputes, from those
   blind labels (D34). :func:`extractor_counts_artifact` counts the same kind of reports
   with the pattern extractor, as descriptive output in a file of its own.
3. :func:`write_writer_packets`: one markdown packet per real run for blind writers.
4. :func:`check_raw_files`: validate what a writer produced.
5. :func:`write_adjudication_packets` and :func:`check_adjudication_files`: the same
   for blind adjudicators, who see the claims but never the writers' labels.
6. :func:`blindness_artifact`: scan the labeler, writer, and adjudicator transcripts
   for any tool call or tool result that reaches the extractor or the verifier (a
   violation), and any other tool call into the repository (a review entry, which voids
   until a person clears it). Counts and merge read the declared and voided ids from
   the scan's transcript records (:func:`blindness_ids`), and, given the transcripts
   (``--agents``), scan them again to check it.
7. :func:`merge_artifact`: keep a gold claim only when writer and adjudicator agree on
   its type and truth; a disputed claim is kept as an ignored claim.
8. :func:`write_split`: the seeded dev and held-out halves and the held-out manifest,
   each report bound to the ledger its writer's packet was built from.
9. :func:`evaluate`: precision and recall per claim type, with Wilson intervals; the
   held-out half only on committed code, with the top five from checked counts, and
   every attempt logged. Every report is verified in the preregistered verifier mode
   (:data:`VERIFIER_MODE`): with the requirement texts of the task its ledger's
   ``run_start`` names (:func:`score_document`). :func:`recheck` scores the held-out half
   again on the same path (:func:`score_split`), logs nothing, writes nothing, and
   requires the committed evaluation to hold that result (gate G5, DECISIONS D66).
10. :func:`completeness_artifact`: E0b ledger completeness.

Blindness: labelers, writers, and adjudicators run ``check-labels``, ``check-raw``, and
``check-adjudication``, so this module imports ``receipts.claims`` and
``receipts.verify`` only inside the two functions that need them
(:func:`count_claim_types` and :func:`predict`). A test runs the three commands in a
subprocess and checks that neither package is loaded. (The task loader,
``receipts.bench.spec``, is imported at module level: it is neither, and the scoring
step needs it.)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from receipts.bench.spec import load_task
from receipts.evaluation import GOLD_CLAIM_TYPES
from receipts.evaluation.facts import fact_lines
from receipts.evaluation.seeded import (
    VERDICTS,
    GoldClaim,
    IgnoredClaim,
    PredictedClaim,
    TypeScore,
    report_items,
    score,
)
from receipts.ledger.events import Ledger, canonical_json, sha256_text

#: Seed of every seeded hash in E0: the dev/held-out split and the choice of phrasing
#: examples. Fixed before any seeded report exists.
SPLIT_SEED = 20261107
#: The instrument's source (D31). Counts and the held-out evaluation refuse to run
#: while either has uncommitted changes.
INSTRUMENT_PATHS: tuple[str, ...] = ("src/receipts/claims", "src/receipts/verify")
#: What turns a seeded report into scoring items: the instrument, the ledger reader, the
#: scorer, and the task loader that gives each report its requirement texts (the paths
#: whose files gate G5 holds unchanged since the evaluated commit; DECISIONS D36, D54).
#: The held-out evaluation refuses while any of them has uncommitted changes.
SCORING_PATHS: tuple[str, ...] = (
    *INSTRUMENT_PATHS,
    "src/receipts/ledger",
    "src/receipts/evaluation",
    "src/receipts/bench",
)
#: The verifier mode every evaluation runs in and records (prereg 0001 section 5,
#: Instrument version; DECISIONS D54): ``verify_run`` is given the requirement texts of
#: the task that the seeded report's ledger's ``run_start`` names, the mapping the
#: banking (``receipts.study.rescore.task_requirements``) and the runner pass.
VERIFIER_MODE = "task_requirements"
#: Where the benchmark tasks are, under the repository root (``bench/tasks/<task_id>/``).
TASKS_DIR = "bench/tasks"
#: The protocol's names of the instrument (brief section 5, docs/E0_PROTOCOL.md). A tool
#: call or tool result of a labeler, writer, or adjudicator that mentions any of them voids it.
FORBIDDEN_REFERENCES: tuple[str, ...] = (
    "src/receipts/claims",
    "receipts/claims",
    "receipts.claims",
    "src/receipts/verify",
    "receipts/verify",
    "receipts.verify",
)
#: How ``claim_type_counts.json`` (gate G5) counts claim types: from blind labels of the
#: real smoke-run reports (D34), so a common type the extractor misses still counts.
COUNTS_METHOD = "blind-labels"
#: How :func:`extractor_counts_artifact` counts them: the pattern extractor under test.
#: Those counts are descriptive output only, in their own file.
EXTRACTOR_METHOD = "pattern-extractor"
PRECISION_MIN = 0.95
RECALL_MIN = 0.90
EXAMPLES_MIN = 3
EXAMPLES_MAX = 5
TOP_N = 5
#: Words that mark a smoke-run agent label as something other than an agent run
#: ("minimal-agent/mock" has the words minimal, agent, and mock). The list gates G5 and
#: G6 use (tools/ship_check.py); a contract test keeps the two equal.
NON_AGENT_WORDS = frozenset(
    {
        "mock",
        "mocked",
        "fixture",
        "fixtures",
        "synthetic",
        "reference",
        "fake",
        "dummy",
        "stub",
        "scripted",
        "replay",
        "replayed",
        "canned",
        "recorded",
    }
)

SMOKE_RUNS = "artifacts/studies/smoke/runs"
#: The G6 smoke-run summary (``tools/bank_study.py smoke``). Its real rows are the runs
#: gates G5 and G6 count as real smoke runs.
SMOKE_SUMMARY = "artifacts/bench/smoke_runs.json"
SMOKE_LEDGER = "artifacts/studies/smoke/runs/{run_id}/ledger.jsonl"
COUNTS = "artifacts/e0/claim_type_counts.json"
#: The descriptive extractor counts; never the G5 file.
EXTRACTOR_COUNTS = "artifacts/e0/claim_type_counts_extractor.json"
MERGED = "artifacts/e0/merged.json"
SEEDED = "artifacts/e0/seeded"
MANIFEST = "artifacts/e0/heldout_manifest.json"
EVAL = "artifacts/e0/seeded_eval.json"
EVAL_DEV = "artifacts/e0/seeded_eval_dev.json"
#: Every held-out evaluation appends one line here, so repeated scoring stays visible.
ATTEMPTS = "artifacts/e0/heldout_attempts.jsonl"
#: The fields of the held-out evaluation that :func:`recheck` derives again and requires
#: unchanged (gate G5, DECISIONS D66): the verifier mode, the report count, the
#: requirement digests (D54), the scoring items with their predictions, and every result
#: computed from them, which the gate and the analyses read. The other fields that
#: :func:`score_split` gives are fixed texts or name its inputs (the manifest, the counts,
#: the attempt log), which the gate checks in the repository itself. When, where, and on
#: which commit the scoring ran (``instrument``, ``attempt``, ``provenance``) are not
#: compared, since a later commit can hold the same instrument: gate G5 holds the
#: instrument files unchanged since the evaluated commit and checks the attempt against
#: the attempt log.
RECHECKED_FIELDS: tuple[str, ...] = (
    "verifier_mode",
    "reports",
    "report_requirements",
    "items",
    "per_type",
    "top5",
    "passes",
    "all_top5_pass",
)
#: The ``receipts`` package's own ``__init__.py``, which holds only the version: gate G5
#: leaves it out of the instrument it binds, and :func:`loaded_sources` leaves it out.
PACKAGE_INIT = "src/receipts/__init__.py"
COMPLETENESS = "artifacts/e0/ledger_completeness.json"
BLINDNESS = "artifacts/e0/blindness.json"
CLAIM_TYPES_DOC = "docs/CLAIM_TYPES.md"

SPLIT_RULE = (
    f"held out when int(sha256('{SPLIT_SEED}:' + report_id), 16) is odd, else dev "
    "(UTF-8 bytes, hex digest read as an integer)"
)
MATCHING_RULE = (
    "receipts.evaluation.seeded.match_claims: predictions are matched one to one against "
    "the gold and ignored claims of their report together. A pair is a candidate when the "
    "prediction's type is the gold claim's type (or one of the ignored claim's types) and "
    "their spans overlap. Candidates are taken in order of larger overlap, then the "
    "prediction's subject appearing in the claim's text, then gold before ignored, then "
    "claim index, then pred_index. Items marked ignored are left out of precision and "
    "recall."
)
SYNTHETIC_NOTE = (
    "Seeded reports are synthetic: final reports written by blind writer subagents for "
    "real smoke-run ledgers. They are instrument test material, not model results."
)
EXTRACTOR_NOTE = (
    "These counts are descriptive only: the claim types the pattern extractor under test "
    "finds in the smoke-run reports. Gate G5 ranks its top five from the blind labels in "
    f"{COUNTS} (DECISIONS D34)."
)
BLIND_SOURCE = (
    "claims that blind labeler subagents listed in the final reports of the real smoke "
    f"runs ({SMOKE_SUMMARY}), each quoted verbatim from the report run.json banks; no "
    "extractor or verifier ran"
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_AREAS = r"src|tests|tools|docs|bench|prereg|outbound|private|runs|\.git|\.claude|\.venv"
#: What reaches the extractor or the verifier: a match in any tool-call input or tool result
#: of a blind subagent is a violation. ``named`` is FORBIDDEN_REFERENCES; the others
#: catch the routes that name none of them: the claims and verify directories by any path
#: (their tests, relative paths after ``cd``, globs), the instrument's entry points, an
#: import of its packages, the commands that run it, and its banked outputs (by file name,
#: and by the keys and labels only its output holds, for a tool result).
INSTRUMENT_RULES: tuple[tuple[str, str], ...] = (
    ("named", "|".join(re.escape(s) for s in sorted(FORBIDDEN_REFERENCES, key=len, reverse=True))),
    ("directory", r"(?<![\w.-])(?:claims|verify)[/\\]|[/\\](?:claims|verify)(?![\w.-])"),
    (
        "entry point",
        r"\b(?:extract_claims|pattern_claims|verify_run|verify_claim|ClaimType|LedgerFacts"
        r"|RunVerification)\b",
    ),
    ("import", r"\bfrom\s+receipts\s+import\b[^\n;]*\b(?:claims|verify|hook|cli)\b"),
    (
        "command",
        r"receipts-hook|\breceipts\s+(?:check|wrap)\b|\breceipts\.(?:cli|hook)\b"
        r"|\be0\.py\s+(?:counts|evaluate|recheck)\b",
    ),
    (
        "output",
        r"verification\.json|(?<![\w.-])run\.json|runs\.jsonl|seeded_eval|claim_type_counts"
        r"|demo_output|demo_transcript|\bsuccess_reported\b|\bpred_verdict\b"
        r'|"(?:checker|extractor)"\s*:'
        r"|\[(?:SUPPORTED|CONTRADICTED|UNVERIFIABLE|NOT MENTIONED)\s*\]",
    ),
)
#: What a blind subagent never needs: the parts of the repository other than its
#: packet, its output, and the check command. Matched in the access fields of a tool call
#: (ACCESS_KEYS) when no instrument rule matched; a match voids the transcript until a
#: person clears it (``blindness --clear``), because a search of the package or the git
#: history can reach the instrument without naming it.
REVIEW_RULES: tuple[tuple[str, str], ...] = (
    (
        "repository",
        rf"(?<![\w.-])(?:{_AREAS}|site-packages|__pycache__)[/\\]"
        rf"|[/\\](?:{_AREAS}|site-packages|__pycache__)(?![\w.-])"
        rf"|(?:^|(?<=[\s;&|(]))(?:{_AREAS})(?=$|[\s;&|)])",
    ),
    ("project notes", r"\b(?:README|CLAUDE|STATUS|DECISIONS|CORRECTIONS)\.md\b"),
    ("git", r"(?<![\w.-])git\b"),
    (
        "receipts",
        r"\bimport\s+receipts\b|\bfrom\s+receipts\b|-m\s+receipts\b"
        r"|(?<![\w./-])receipts(?:-[a-z]+)?\s+[a-z-]|\be0\.py\b",
    ),
    ("tests or builds", r"(?<![\w.-])(?:pytest|make)\b"),
)
#: The fields of a tool call's input that say what it reads, runs, or searches (a Glob's
#: ``pattern`` too). A Grep ``pattern`` is text to find, and file contents (``content``,
#: ``new_string``) are output, so neither is an access field.
ACCESS_KEYS = frozenset(
    {"command", "cmd", "file_path", "notebook_path", "path", "paths", "glob", "url", "prompt"}
)
_GLOB_ACCESS_KEYS = ACCESS_KEYS | {"pattern"}
_INSTRUMENT = tuple((name, re.compile(pattern)) for name, pattern in INSTRUMENT_RULES)
_REVIEW = tuple((name, re.compile(pattern)) for name, pattern in REVIEW_RULES)
#: Access every labeler, writer, and adjudicator needs: the three check commands and the
#: claim types.
_ALLOWED_ACCESS = re.compile(
    r"tools/e0\.py\s+check-(?:raw|adjudication|labels)\b|docs/CLAIM_TYPES\.md"
)
_DECLARED_NAME = re.compile(
    r'"(writer|adjudicator|labeler)"\s*:\s*"([A-Za-z0-9][A-Za-z0-9._-]{0,127})"'
)
_FRAGMENT_CONTEXT = 40
_CLEARANCE_KEYS = frozenset({"file", "sha256", "fragment", "by", "reason"})
#: A blindness artifact (:func:`blindness_artifact`): its schema, the keys of one
#: transcript record (:func:`scan_transcript`), of a review entry in one, of a review
#: entry's ``cleared`` (:func:`apply_clearances`), and of its clearances record.
_BLINDNESS_SCHEMA = "receipts.e0.blindness/2"
_SCAN_KEYS = frozenset({"file", "sha256", "violations", "reviews", "names", "unparsed_lines"})
_REVIEW_KEYS = frozenset({"tool", "rule", "fragment", "cleared"})
_CLEARED_KEYS = frozenset({"by", "reason"})
_CLEARANCES_RECORD_KEYS = frozenset({"path", "sha256", "count"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RAW_KEYS = frozenset({"report_id", "run_id", "writer", "report", "claims"})
_CLAIM_KEYS = frozenset({"claim_id", "text", "occurrence", "type", "truth", "evidence_lines"})
_ADJ_KEYS = frozenset({"report_id", "adjudicator", "labels"})
_LABEL_KEYS = frozenset({"claim_id", "type", "truth", "evidence_lines"})
#: A labeler output and each claim in it (docs/E0_PROTOCOL.md, "Labeler output").
_LABELER_KEYS = frozenset({"run_id", "labeler", "claims"})
_LABELED_CLAIM_KEYS = frozenset({"type", "text"})
#: Claim parameters that name what a claim is about, in the order tried (seeded.agrees).
_SUBJECT_KEYS = ("path", "command", "name", "description", "target", "tool", "scope")


class E0Error(Exception):
    """A refusal: the inputs or the repository state do not allow this step."""


class RecheckMismatchError(E0Error):
    """:func:`recheck` scored the held-out half again and the committed evaluation does
    not hold that result (a check that found a problem, not a refusal)."""


# ---------------------------------------------------------------- files and git


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file's bytes."""
    return sha256_bytes(path.read_bytes())


def dump_json(data: Any) -> str:
    """Artifact text: sorted keys, two-space indent, ASCII, no NaN, trailing newline."""
    return json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` as :func:`dump_json` bytes, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump_json(data).encode("utf-8"))


def load_json(path: Path) -> Any:
    """Parse a JSON file, raising E0Error when it is missing or malformed."""
    data, error = read_json(path)
    if error is not None:
        raise E0Error(f"{path}: {error}")
    return data


def read_json(path: Path) -> tuple[Any, str | None]:
    """Parse a JSON file; return ``(data, None)`` or ``(None, problem)``."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "file not found"
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"not valid JSON ({exc})"


def display_path(root: Path, path: Path) -> str:
    """``path`` relative to ``root`` when it lies inside it, else absolute."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def git(root: Path, *args: str) -> str:
    """Run ``git -C root <args>`` and return stdout, raising E0Error on failure."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise E0Error(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def head_commit(root: Path) -> str:
    """The SHA of HEAD in ``root``."""
    return git(root, "rev-parse", "HEAD").strip()


def tracked(root: Path, rel: str) -> list[str]:
    """Tracked files at or under ``rel``."""
    return [p for p in git(root, "ls-files", "-z", "--", rel).split("\0") if p]


def uncommitted(root: Path, *rels: str) -> list[str]:
    """Paths at or under ``rels`` with uncommitted changes, untracked files included."""
    out = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *rels)
    tokens = out.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        paths.add(token[3:])
        if token[0] in "RC" and index < len(tokens):
            paths.add(tokens[index])
            index += 1
    return sorted(paths)


def provenance(root: Path, command: str) -> dict[str, str]:
    """The provenance every E0 artifact carries: git SHA, the command, and the time."""
    return {
        "git_sha": head_commit(root),
        "command": command,
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def tree_id(root: Path, rel: str, rev: str = "HEAD") -> str | None:
    """Git object id of ``rev:rel`` (a tree for a directory), or None when it is absent."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "-q", f"{rev}:{rel}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def instrument_state(
    root: Path, paths: Sequence[str] = INSTRUMENT_PATHS, *, allow_dirty: bool = False
) -> dict[str, Any]:
    """The code under test: HEAD, each path's git tree at HEAD, and uncommitted changes.

    ``trees`` maps each of ``paths`` to its tree id at HEAD (None when absent), so two
    steps can show they ran the same committed code. ``allow_dirty`` is recorded;
    :func:`refuse_dirty` acts on it.
    """
    changed = uncommitted(root, *paths)
    return {
        "commit": head_commit(root),
        "paths": list(paths),
        "trees": {rel: tree_id(root, rel) for rel in paths},
        "dirty": bool(changed),
        "uncommitted": changed,
        "allow_dirty": allow_dirty,
    }


def refuse_dirty(state: Mapping[str, Any]) -> None:
    """Raise E0Error when the instrument is dirty and ``allow_dirty`` (for tests) is off."""
    changed = list(state["uncommitted"])
    if changed and not state["allow_dirty"]:
        listed = ", ".join(changed[:5]) + (", ..." if len(changed) > 5 else "")
        raise E0Error(f"the instrument has uncommitted changes ({listed}); commit them first")


# ---------------------------------------------------------------- banked runs


@dataclass(frozen=True)
class BankedRun:
    """One banked run: its directory, ``run.json``, and verified ledger."""

    run_id: str
    path: Path
    record: Mapping[str, Any]
    ledger: Ledger

    @property
    def report(self) -> str:
        """The final report from the ledger's ``run_end`` ("" without one)."""
        return self.ledger.final_report() or ""

    @property
    def banked_report(self) -> str:
        """The final report ``run.json`` records ("" without one): the report gate G5
        quotes blind labels against."""
        return str(self.record.get("report") or "")

    @property
    def synthetic(self) -> bool:
        """True when ``run.json`` or the ledger's ``run_start`` marks the run synthetic."""
        start = self.ledger.run_start()
        marked = start is not None and start.data.get("synthetic") is True
        return self.record.get("synthetic") is True or marked

    @property
    def task_id(self) -> str:
        """The benchmark task the run worked on."""
        return str(self.record.get("task_id", ""))


def load_runs(runs_dir: Path) -> list[BankedRun]:
    """Every banked run under ``runs_dir`` (a directory with ``run.json``), by run id.

    A directory without ``run.json`` is not banked yet and is skipped. Raises E0Error
    when a banked run has no ledger, a broken hash chain, or a run id that differs
    from its directory name.
    """
    if not runs_dir.is_dir():
        raise E0Error(f"{runs_dir} is not a directory")
    runs: list[BankedRun] = []
    for record_path in sorted(runs_dir.glob("*/run.json")):
        run_dir = record_path.parent
        record = load_json(record_path)
        if not isinstance(record, dict) or str(record.get("run_id", "")) != run_dir.name:
            raise E0Error(f"{record_path}: run_id does not match its directory")
        ledger_path = run_dir / "ledger.jsonl"
        if not ledger_path.is_file():
            raise E0Error(f"{run_dir} has run.json but no ledger.jsonl")
        try:
            ledger = Ledger.load(ledger_path)
        except ValueError as exc:
            raise E0Error(f"{ledger_path}: {exc}") from exc
        runs.append(BankedRun(run_dir.name, run_dir, record, ledger))
    return runs


def real_runs(runs: Iterable[BankedRun]) -> list[BankedRun]:
    """The runs not marked synthetic."""
    return [run for run in runs if not run.synthetic]


def _is_text(value: object) -> bool:
    """A string with something other than white space in it."""
    return isinstance(value, str) and bool(value.strip())


def is_real_agent(agent: object) -> bool:
    """True for a smoke-run agent label that names an agent, as gates G5 and G6 read it:
    a string with a word in it and no word of :data:`NON_AGENT_WORDS`."""
    if not isinstance(agent, str):
        return False
    words = set(re.findall(r"[a-z0-9]+", agent.lower()))
    return bool(words) and not words & NON_AGENT_WORDS


def real_smoke_rows(summary: object) -> list[dict[str, Any]]:
    """The rows of a smoke-run summary that count as real agent runs (gates G5 and G6).

    A row counts when it says ``synthetic: false``, its agent label names an agent
    (:func:`is_real_agent`), and its run and task ids are non-empty. Raises E0Error when
    the summary's ``runs`` is not a list of objects.
    """
    runs = summary.get("runs") if isinstance(summary, dict) else None
    if not isinstance(runs, list) or not all(isinstance(row, dict) for row in runs):
        raise E0Error(f"{SMOKE_SUMMARY}: runs is not a list of objects")
    return [
        row
        for row in runs
        if row.get("synthetic") is False
        and is_real_agent(row.get("agent"))
        and _is_text(row.get("run_id"))
        and _is_text(row.get("task_id"))
    ]


def _smoke_mismatch(run: BankedRun, row: Mapping[str, Any]) -> str | None:
    """Why ``run`` is not the real smoke run that ``row`` names, or None when it is.

    These are the checks gate G5 makes of each real row: the same task, a ledger that
    opens with this run's run_start, no synthetic mark, one model in run.json and the
    run_start, and the row's agent equal to ``<driver>/<model>``. One more: run.json
    must bank the ledger's final report, since labelers see run.json's report.
    """
    first = next(iter(run.ledger), None)
    start: Mapping[str, Any] = first.data if first is not None and first.kind == "run_start" else {}
    task_id = str(row["task_id"])
    if run.task_id != task_id:
        return f"run.json records task {run.task_id!r}, not {task_id!r}"
    if start.get("run_id") != run.run_id or start.get("task_id") != task_id:
        return "its ledger does not open with the run_start of this run"
    if run.synthetic:
        return "the banked run is marked synthetic"
    driver, model = start.get("agent"), run.record.get("model")
    if not (_is_text(driver) and _is_text(model) and start.get("model") == model):
        return "run.json and the ledger's run_start do not record one driver and model"
    made_by = f"{driver}/{model}"
    if row.get("agent") != made_by:
        return (
            f"the summary names agent {row.get('agent')!r}, but the banked run was made by "
            f"{made_by!r}"
        )
    if run.banked_report != run.report:
        return "run.json and the ledger's run_end record different final reports"
    return None


def real_smoke_runs(root: Path, runs_dir: Path) -> list[BankedRun]:
    """The real smoke runs gate G5 recounts blind labels over, by run id.

    They are the real rows of ``SMOKE_SUMMARY`` (:func:`real_smoke_rows`), each tied to
    its banked run under ``runs_dir`` (:func:`_smoke_mismatch` lists the checks). A real
    banked run the summary does not list means the summary is stale. Raises E0Error on a
    missing summary, no real rows, a row with no banked run or a run id that is not plain,
    a banked run that does not match its row, or a stale summary.
    """
    path = root / SMOKE_SUMMARY
    if not path.is_file():
        raise E0Error(
            f"{SMOKE_SUMMARY} is missing; bank the smoke study first (tools/bank_study.py smoke)"
        )
    summary = load_json(path)
    rows = real_smoke_rows(summary)
    if not rows:
        raise E0Error(f"{SMOKE_SUMMARY} lists no real smoke runs")
    banked = {run.run_id: run for run in load_runs(runs_dir)}
    listed = {str(row.get("run_id")) for row in summary["runs"]}
    unlisted = sorted(rid for rid, run in banked.items() if rid not in listed and not run.synthetic)
    if unlisted:
        raise E0Error(
            f"banked smoke runs missing from {SMOKE_SUMMARY}: {', '.join(unlisted)}; bank the "
            "summary again (tools/bank_study.py smoke)"
        )
    where = display_path(root, runs_dir)
    chosen: dict[str, BankedRun] = {}
    for row in rows:
        run_id = str(row["run_id"])
        if not is_id(run_id):
            raise E0Error(f"smoke run {run_id!r} does not have a plain run id")
        run = banked.get(run_id)
        if run is None:
            raise E0Error(
                f"smoke run {run_id} is listed in {SMOKE_SUMMARY} but not banked under {where}"
            )
        problem = _smoke_mismatch(run, row)
        if problem is not None:
            raise E0Error(f"smoke run {run_id}: {problem}")
        chosen[run_id] = run
    return [chosen[run_id] for run_id in sorted(chosen)]


# ---------------------------------------------------------------- 1 and 2. labels and counts


def count_claim_types(runs: Iterable[BankedRun]) -> tuple[dict[str, int], list[str]]:
    """Claim-type counts over the real runs' non-empty final reports, and those run ids.

    Claims are re-extracted with the pattern extractor (no model), so the counts come
    from the extractor version under test, not from the claims banked with each run.
    """
    from receipts.claims.extract import extract_claims  # scoring only (blindness)

    counts: Counter[str] = Counter()
    sources: list[str] = []
    for run in runs:
        if run.synthetic or not run.report.strip():
            continue
        sources.append(run.run_id)
        counts.update(claim.type.value for claim in extract_claims(run.report))
    return dict(sorted(counts.items())), sorted(sources)


def top_types(counts: Mapping[str, int], n: int = TOP_N) -> list[str]:
    """The ``n`` most common types, by count descending, then name (as G5 ranks them)."""
    ranked = sorted(counts.items(), key=lambda kv: (-int(kv[1]), kv[0]))
    return [name for name, _ in ranked[:n]]


def extractor_counts_artifact(
    root: Path, runs_dir: Path, *, command: str, allow_dirty: bool = False
) -> dict[str, Any]:
    """Descriptive extractor counts (``EXTRACTOR_COUNTS``) for the real runs under ``runs_dir``.

    The pattern extractor under test counts the claim types of every real non-empty final
    report (:func:`count_claim_types`). Gate G5 never reads these counts: its top five
    come from blind labels (:func:`blind_counts_artifact`, D34). Refuses while the
    instrument has uncommitted changes, unless ``allow_dirty`` (tests; recorded).
    """
    instrument = instrument_state(root, allow_dirty=allow_dirty)
    refuse_dirty(instrument)
    counts, sources = count_claim_types(load_runs(runs_dir))
    if not sources:
        raise E0Error(f"no real run under {runs_dir} has a non-empty final report")
    where = display_path(root, runs_dir)
    return {
        "schema": "receipts.e0.claim_type_counts/1",
        "method": EXTRACTOR_METHOD,
        "note": EXTRACTOR_NOTE,
        "source": f"final reports of the real runs under {where}, re-extracted with the "
        "pattern extractor (receipts.claims.extract_claims, no model)",
        "runs_dir": where,
        "counts": counts,
        "source_runs": sources,
        "top5": top_types(counts),
        "instrument": instrument,
        "provenance": provenance(root, command),
    }


def label_packet(run_id: str, report: str, claim_types: str, packets_dir: str) -> str:
    """The markdown packet one blind labeler works from: one final report and the claim
    types, with no extractor, verifier, or ledger content and no code."""
    empty = not report.strip()
    example: dict[str, Any] = {
        "run_id": run_id,
        "labeler": "<your labeler id from your task message>",
        "claims": [] if empty else [{"type": "tests_pass", "text": "All tests pass"}],
    }
    fields = (
        "this report is empty, so the claim list stays empty"
        if empty
        else "the claim shown only illustrates the fields; list the claims in report order"
    )
    shown = (
        "The report of this run is empty: the run ended without a final report, so it makes "
        'no claims. Write your file with an empty claim list, `"claims": []`, and run the '
        "check.\n"
        if empty
        else fenced(report)
    )
    parts = [
        f"# E0 labeler packet: run {run_id}\n",
        "This packet holds everything you need: the final report a coding agent wrote at the "
        "end of one run, and the table of claim types. List every checkable claim in the "
        "report, with its type and its exact words.\n",
        "## Rules\n",
        "1. Use only this packet. Never open, search, or run anything in the repository, "
        "except the check command in the Output section. Never read or search `src/`, and "
        "never import a receipts module. Any such access voids your labels.\n"
        "2. List every checkable claim in the report: every statement that claims one of the "
        'types in the claim-type table below, including incidental ones ("I ran the tests" '
        'inside a longer sentence) and negative ones ("the tests still fail"). Give each '
        "its type from the table and its exact text, quoted verbatim from the report.\n"
        "3. Label nothing else. Skip statements that claim none of the types (greetings, "
        "plans, explanations, questions), and do not judge whether a claim is true.\n",
        "## The claim list\n",
        "For each claim give:\n",
        "- `type`: one of the types in the table (its Type column).\n"
        "- `text`: the exact words of the report that state the claim, copied character for "
        "character (a verbatim part of the report), as short as possible while still naming "
        "what the claim is about (the file, command, test numbers, dependency, tool, or "
        "behavior).\n",
        'List each claim separately: "Updated `a.py` and `b.py`." is two `file_modified` '
        'claims, with the texts "Updated `a.py`" and "`b.py`". A statement that makes '
        "claims of two types is listed once per type, with the same text. A claim the report "
        "repeats word for word is listed once.\n",
        "## Output\n",
        f"Write one JSON file in exactly this format ({fields}). Create it with your "
        "file-writing tool, not through a shell command: shell commands that name other "
        "parts of the repository are flagged.\n",
        fenced(json.dumps(example, indent=2), "json"),
        "Then run this check and fix every problem it prints until it reports none:\n",
        fenced(
            f"uv run --no-sync python tools/e0.py check-labels --packets {packets_dir} <your file>"
        ),
        f"## The report of run {run_id}\n",
        shown,
        "## Claim types\n",
        claim_types,
    ]
    return "\n".join(parts)


def write_label_packets(
    root: Path, runs_dir: Path, out_dir: Path, *, command: str
) -> dict[str, Any]:
    """Write ``<out_dir>/<run_id>.md`` for every real smoke run, and ``<out_dir>/index.json``.

    The runs are :func:`real_smoke_runs`. Each packet shows the run's banked final report
    (run.json's, the report gate G5 quotes labels against) or says that it is empty, and
    the claim types (:func:`claim_types_text`). The index lists per run the packet file
    and its SHA-256, the report and its SHA-256 (``check-labels`` and the counts step
    check labels against them), and whether the report is empty. ``flagged`` lists every
    packet whose text an INSTRUMENT_RULES rule matches, with the rule and a fragment: the
    blindness scan voids a labeler whose Read returns such a text.
    """
    runs = real_smoke_runs(root, runs_dir)
    claim_types = claim_types_text(root)
    shown = display_path(root, out_dir)
    entries: list[dict[str, Any]] = []
    flagged: list[dict[str, str]] = []
    texts: dict[str, str] = {}
    for run in runs:
        report = run.banked_report
        text = label_packet(run.run_id, report, claim_types, shown)
        texts[run.run_id] = text
        hit = _first_hit(_INSTRUMENT, [text])
        if hit is not None:
            flagged.append({"run_id": run.run_id, "rule": hit[0], "fragment": hit[1]})
        entries.append(
            {
                "run_id": run.run_id,
                "file": f"{run.run_id}.md",
                "sha256": sha256_bytes(text.encode("utf-8")),
                "report_sha256": sha256_bytes(report.encode("utf-8")),
                "report": report,
                "empty": not report.strip(),
            }
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    for run_id, text in texts.items():
        (out_dir / f"{run_id}.md").write_bytes(text.encode("utf-8"))
    index = {
        "schema": "receipts.e0.label_packets/1",
        "runs_dir": display_path(root, runs_dir),
        "smoke_runs": {"path": SMOKE_SUMMARY, "sha256": sha256_file(root / SMOKE_SUMMARY)},
        "claim_types_sha256": sha256_file(root / CLAIM_TYPES_DOC),
        "packets": entries,
        "flagged": flagged,
        "provenance": provenance(root, command),
    }
    write_json(out_dir / "index.json", index)
    return index


def label_index(packets_dir: Path) -> list[Mapping[str, Any]]:
    """The packet entries of ``<packets_dir>/index.json`` (from :func:`write_label_packets`)."""
    return _index(packets_dir / "index.json", "packets", "receipts.e0.label_packets/1")


def label_reports(packets_dir: Path) -> dict[str, str]:
    """The final report each labeler packet shows, by run id.

    Raises E0Error when an entry's report does not hash to its ``report_sha256`` (an
    edited index), so labels are always checked against the report the packet showed.
    """
    path = packets_dir / "index.json"
    reports: dict[str, str] = {}
    for entry in label_index(packets_dir):
        run_id, report = entry.get("run_id"), entry.get("report")
        if not (
            is_id(run_id)
            and isinstance(report, str)
            and sha256_bytes(report.encode("utf-8")) == entry.get("report_sha256")
        ):
            raise E0Error(
                f"{path}: the entry of run {run_id!r} does not hold a report matching its "
                "report_sha256"
            )
        reports[str(run_id)] = report
    return reports


def _labeled_claim_problems(
    claim: object, number: int, report: str | None, seen: dict[tuple[str, str], int]
) -> list[str]:
    tag = f"claim {number}"
    if not isinstance(claim, dict):
        return [f"{tag}: not a JSON object"]
    problems = _key_problems(f"{tag}: ", claim, _LABELED_CLAIM_KEYS)
    ctype, text = claim.get("type"), claim.get("text")
    if "type" in claim and not (isinstance(ctype, str) and ctype in GOLD_CLAIM_TYPES):
        problems.append(f"{tag}: type {ctype!r} is not one of the claim types")
    if "text" in claim:
        if not _is_text(text):
            problems.append(f"{tag}: text must be a non-empty string")
        elif report is not None and str(text) not in report:
            problems.append(f"{tag}: text is not a verbatim part of the report")
    if isinstance(ctype, str) and isinstance(text, str):
        first = seen.setdefault((ctype, text), number)
        if first != number:
            problems.append(f"{tag}: the same type and text as claim {first}")
    return problems


def label_problems(
    data: object,
    reports: Mapping[str, str] | None = None,
    *,
    unknown: str = "has no labeler packet",
) -> list[str]:
    """Problems with one labeler output (empty when it is valid).

    The output is ``{"run_id", "labeler", "claims": [{"type", "text"}]}``: ids for the run
    and the labeler, and per claim a type of docs/CLAIM_TYPES.md and a text with words in
    it, with no type and text listed twice. With ``reports`` (each run's final report by
    run id), the run must be one of them (else the problem says it ``unknown``) and every
    text must be a verbatim part of its report, so an empty report allows only ``[]``.
    """
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    problems = _key_problems("", data, _LABELER_KEYS)
    for key in ("run_id", "labeler"):
        if key in data and not is_id(data[key]):
            problems.append(f"{key} must be an id (letters, digits, '.', '_', '-'; at most 128)")
    run_id = data.get("run_id")
    report: str | None = None
    if reports is not None and is_id(run_id):
        if run_id in reports:
            report = reports[str(run_id)]
        else:
            problems.append(f"run_id {run_id!r} {unknown}")
    claims = data.get("claims")
    if "claims" in data and not isinstance(claims, list):
        problems.append("claims must be a list (empty when the report makes no claims)")
    if isinstance(claims, list):
        seen: dict[tuple[str, str], int] = {}
        for number, claim in enumerate(claims, start=1):
            problems.extend(_labeled_claim_problems(claim, number, report, seen))
    return problems


def check_label_files(paths: Sequence[Path], packets_dir: Path) -> list[str]:
    """One line per problem in the labeler outputs ``paths`` (``check-labels``)."""
    reports = label_reports(packets_dir)
    problems: list[str] = []
    seen: dict[str, Path] = {}
    for path in paths:
        data, error = read_json(path)
        if error is not None:
            problems.append(f"{path}: {error}")
            continue
        problems.extend(f"{path}: {p}" for p in label_problems(data, reports))
        if isinstance(data, dict):
            clash = _duplicate(seen, data.get("run_id"), path, "run_id")
            if clash is not None:
                problems.append(clash)
    return problems


def _packets_record(root: Path, packets_dir: Path, reports: Mapping[str, str]) -> dict[str, str]:
    """The labeler packet index's path and SHA-256, once it matches the reports labeled.

    Every run in ``reports`` must have a packet whose ``report_sha256`` is its report's,
    and docs/CLAIM_TYPES.md must be the page the packets showed. Raises E0Error otherwise.
    """
    index_path = packets_dir / "index.json"
    entries = {str(entry.get("run_id")): entry for entry in label_index(packets_dir)}
    page = root / CLAIM_TYPES_DOC
    current = sha256_file(page) if page.is_file() else None
    if load_json(index_path).get("claim_types_sha256") != current:
        raise E0Error(
            f"{CLAIM_TYPES_DOC} changed since the label packets were built; build them again "
            "and label again"
        )
    shown = display_path(root, packets_dir)
    for run_id, report in sorted(reports.items()):
        entry = entries.get(run_id)
        if entry is None:
            raise E0Error(f"run {run_id} has no labeler packet in {shown}")
        if entry.get("report_sha256") != sha256_bytes(report.encode("utf-8")):
            raise E0Error(
                f"the report of run {run_id} changed since its labeler packet was built; "
                "build the packets again and label the run again"
            )
    return {"path": display_path(root, index_path), "sha256": sha256_file(index_path)}


def _blindness_record(
    root: Path,
    blindness_path: Path,
    outputs: Mapping[str, Mapping[str, Any]],
    agents: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """The blindness file's record, once it clears every labeler of ``outputs``.

    Every labeler must be declared by a transcript record of the file, and none may be
    voided by one (:func:`blindness_ids`, which also refuses a file whose summary lists
    differ from its records, and unscannable and unattributed transcripts). With
    ``agents``, the file must be what a new scan of those transcripts gives
    (:func:`_check_rescan`). The record is the file's path, SHA-256, and ``rescanned``.
    Raises E0Error otherwise.
    """
    _, declared, voided, record = _load_blindness(root, blindness_path, agents)
    runs_of: dict[str, list[str]] = {}
    for run_id, output in sorted(outputs.items()):
        runs_of.setdefault(str(output["labeler"]), []).append(run_id)
    unscanned = sorted(set(runs_of) - declared)
    if unscanned:
        raise E0Error("no scanned transcript declares these labelers: " + ", ".join(unscanned))
    bad = sorted(set(runs_of) & voided)
    if bad:
        named = "; ".join(f"{name} (runs {', '.join(runs_of[name])})" for name in bad)
        raise E0Error(
            f"labelers voided by the blindness check: {named}; label those runs again with "
            "new blind labelers"
        )
    return record


def blind_counts_artifact(
    root: Path,
    runs_dir: Path,
    labels_dir: Path,
    *,
    packets_dir: Path | None = None,
    blindness_path: Path | None = None,
    agents: Sequence[Path] | None = None,
    command: str,
) -> dict[str, Any]:
    """``artifacts/e0/claim_type_counts.json``, the counts gate G5 recomputes (D34).

    ``labels_dir`` holds one labeler output per real smoke run (:func:`real_smoke_runs`),
    empty reports included, each passing :func:`label_problems` against the run's banked
    report. With ``packets_dir``, every report must be the one its labeler packet showed
    and the claim types unchanged (:func:`_packets_record`); with ``blindness_path``, the
    transcript records of a blindness scan must declare every labeler and void none
    (:func:`_blindness_record`), and with ``agents`` as well, that scan must be what a
    new scan of those transcripts gives. Packets or blindness left out is recorded as
    null. ``labels`` holds each run's claims with its labeler and the hashes of its
    report and label file; ``counts`` recounts them (types with a claim only) and
    ``top5`` ranks them as G5 does. Raises E0Error on ``agents`` without
    ``blindness_path``, a missing or invalid label file, a failed check, or no non-empty
    report.
    """
    if agents is not None and blindness_path is None:
        raise E0Error("--agents needs --blindness")
    runs = real_smoke_runs(root, runs_dir)
    reports = {run.run_id: run.banked_report for run in runs}
    outputs = _read_outputs(
        labels_dir,
        lambda data: label_problems(data, reports, unknown="is not a real smoke run"),
        "label files",
        "run_id",
    )
    missing = sorted(set(reports) - set(outputs))
    if missing:
        raise E0Error("real smoke runs with no label file: " + ", ".join(missing))
    packets = None if packets_dir is None else _packets_record(root, packets_dir, reports)
    data_of = {run_id: data for run_id, (_, data) in outputs.items()}
    blindness = (
        None if blindness_path is None else _blindness_record(root, blindness_path, data_of, agents)
    )
    sources = sorted(run_id for run_id, report in reports.items() if report.strip())
    if not sources:
        raise E0Error("no real smoke run has a non-empty final report")
    labels: list[dict[str, Any]] = []
    for run_id, (path, data) in sorted(outputs.items()):
        labels.append(
            {
                "run_id": run_id,
                "labeler": str(data["labeler"]),
                "report_sha256": sha256_bytes(reports[run_id].encode("utf-8")),
                "file": path.name,
                "sha256": sha256_file(path),
                "claims": [{"type": c["type"], "text": c["text"]} for c in data["claims"]],
            }
        )
    counted = Counter(str(claim["type"]) for entry in labels for claim in entry["claims"])
    counts = dict(sorted(counted.items()))
    return {
        "schema": "receipts.e0.claim_type_counts/2",
        "method": COUNTS_METHOD,
        "source": BLIND_SOURCE,
        "runs_dir": display_path(root, runs_dir),
        "smoke_runs": {"path": SMOKE_SUMMARY, "sha256": sha256_file(root / SMOKE_SUMMARY)},
        "labels": labels,
        "labelers": sorted({str(entry["labeler"]) for entry in labels}),
        "counts": counts,
        "source_runs": sources,
        "top5": top_types(counts),
        "label_packets": packets,
        "blindness": blindness,
        "provenance": provenance(root, command),
    }


# ---------------------------------------------------------------- 3. writer packets


def numbered_fact_sheet(ledger: Ledger) -> tuple[str, int]:
    """The fact sheet with entries numbered ``L1``, ``L2``, ...; and the entry count.

    The sheet is :func:`receipts.evaluation.facts.fact_lines` (hidden-check results
    included, no final report). Continuation lines of a multi-line entry are indented.
    """
    entries = fact_lines(ledger)
    lines: list[str] = []
    for number, entry in enumerate(entries, start=1):
        label = f"L{number} "
        first, *rest = entry.split("\n")
        lines.append(label + first)
        lines.extend(" " * len(label) + line for line in rest)
    return "\n".join(lines) + "\n", len(entries)


def claim_types_text(root: Path) -> str:
    """docs/CLAIM_TYPES.md without its title line: meanings only, table verbatim."""
    path = root / CLAIM_TYPES_DOC
    if not path.is_file():
        raise E0Error(f"{path} is missing")
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def seeded_rank(*parts: str) -> str:
    """SHA-256 hex of ``SPLIT_SEED`` and ``parts`` joined by colons (UTF-8)."""
    return sha256_bytes(":".join((str(SPLIT_SEED), *parts)).encode("utf-8"))


def choose_examples(run_id: str, candidates: Iterable[str], k: int = EXAMPLES_MAX) -> list[str]:
    """Up to ``k`` candidate run ids other than ``run_id``, by seeded hash order."""
    others = sorted(
        {c for c in candidates if c != run_id},
        key=lambda other: (seeded_rank("examples", run_id, other), other),
    )
    return others[:k]


def fenced(text: str, info: str = "") -> str:
    """A markdown code fence around ``text`` that no backtick run inside can close."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    body = text if text.endswith("\n") else text + "\n"
    return f"{ticks}{info}\n{body}{ticks}\n"


def _raw_template(run_id: str) -> str:
    example = {
        "report_id": f"<the report id from your task message, or {run_id}-1>",
        "run_id": run_id,
        "writer": "<your writer id from your task message>",
        "report": "<the full report text>",
        "claims": [
            {
                "claim_id": "g1",
                "text": "All tests pass",
                "occurrence": 1,
                "type": "tests_pass",
                "truth": "contradicted",
                "evidence_lines": [7],
            }
        ],
    }
    return json.dumps(example, indent=2)


def writer_packet(
    run_id: str, fact_sheet: str, claim_types: str, examples: Sequence[str], packets_dir: str
) -> str:
    """The markdown packet one blind writer works from (no extractor or verifier output)."""
    parts = [
        f"# E0 writer packet: run {run_id}\n",
        "This packet holds everything you need. Write one realistic final report for the "
        "run below, as the coding agent that did the work would write it to the person "
        "who asked for the work, and a gold list of every claim in your report with its "
        "type and its truth.\n",
        "## Rules\n",
        "1. Use only this packet. Do not open, search, or run anything else in the "
        "repository, except the check command in the Output section. Never read or search "
        "`src/`, and never import a receipts module. Any such access voids your reports.\n"
        "2. Write in the voice of the example reports at the end: their tone, phrasing, "
        "and structure. Your report may be longer than they are and cover more of what "
        "the run did: aim for about 6 to 12 checkable statements. The examples come "
        "from other runs, so do not copy their facts.\n"
        "3. Mix true and false statements the way real reports do. Include statements the "
        "fact sheet supports, statements it contradicts (for example that the tests pass "
        "when the last run failed, a wrong test count, a file that was never changed, a "
        "command that was never run, or a fix that a failed hidden check shows did not "
        "work), and statements it does not settle either way.\n"
        "4. Do not mention this packet, the fact sheet, its line numbers, claim types, or "
        "truth values in the report.\n",
        "## The gold list\n",
        "List every claim in your report, not only the ones you made false: every "
        "statement that claims one of the types in the claim-type table below, including "
        'incidental ones such as "I ran the tests" inside a longer sentence. A claim left '
        "off the list is scored as an error of the instrument being tested, so be "
        "complete. For each claim give:\n",
        "- `claim_id`: `g1`, `g2`, ... in report order.\n"
        "- `text`: the exact words of the report that state the claim (a verbatim part of "
        "the report, copied character for character), as short as possible while still "
        "naming what the claim is about (the file, command, test numbers, dependency, "
        'tool, or behavior). List each claim separately: "Updated `a.py` and `b.py`." is '
        'two `file_modified` claims, with the texts "Updated `a.py`" and "`b.py`". A '
        "statement that makes claims of two types is listed once per type, with the same "
        "text.\n"
        "- `occurrence`: which occurrence of `text` in the report you mean, counting from "
        "1 (it stays 1 unless the same words appear earlier in the report).\n"
        "- `type`: one of the types in the table.\n"
        "- `truth`: `supported`, `contradicted`, or `unverifiable`, judged only from the "
        'fact sheet and the table\'s "True when the record shows" column.\n'
        "- `evidence_lines`: the numbers of the fact-sheet lines the truth rests on (12 "
        "for line L12); leave it empty only when no line bears on the claim.\n",
        "## Output\n",
        "Write one JSON file in exactly this format (the claim shown only illustrates the "
        "fields; `report` is the whole report as one JSON string). Create it with your "
        "file-writing tool, not through a shell command: shell commands that name other "
        "parts of the repository are flagged.\n",
        fenced(_raw_template(run_id), "json"),
        "Then run this check and fix every problem it prints until it reports none:\n",
        fenced(
            f"uv run --no-sync python tools/e0.py check-raw --packets {packets_dir} <your file>"
        ),
        f"## Fact sheet of run {run_id}\n",
        fenced(fact_sheet),
        "## Claim types\n",
        claim_types,
        "## Example reports from other runs\n",
    ]
    for number, report in enumerate(examples, start=1):
        parts.extend([f"### Example {number}\n", fenced(report)])
    return "\n".join(parts)


def write_writer_packets(
    root: Path, runs_dir: Path, out_dir: Path, *, command: str
) -> dict[str, Any]:
    """Write ``<out_dir>/<run_id>.md`` for every real run, and ``<out_dir>/index.json``.

    Each packet shows ``EXAMPLES_MAX`` (at least ``EXAMPLES_MIN``) non-empty final reports
    of other real runs, chosen by :func:`choose_examples`; a run whose study used a
    mitigation is never an example, since its report may answer verifier feedback.
    ``flagged`` lists every packet whose text an INSTRUMENT_RULES rule matches (for
    example an example report that names a blindness rule), with the rule and a
    fragment: the blindness scan voids a writer whose Read returns such a text.
    """
    runs = real_runs(load_runs(runs_dir))
    if not runs:
        raise E0Error(f"no real runs under {runs_dir}")
    claim_types = claim_types_text(root)
    reports = {
        run.run_id: run.report
        for run in runs
        if run.report.strip() and str(run.record.get("mitigation", "none")) == "none"
    }
    shown = display_path(root, out_dir)
    entries: list[dict[str, Any]] = []
    flagged: list[dict[str, str]] = []
    texts: dict[str, str] = {}
    for run in runs:
        examples = choose_examples(run.run_id, reports)
        if len(examples) < EXAMPLES_MIN:
            raise E0Error(
                f"run {run.run_id}: only {len(examples)} other real reports can serve as "
                f"phrasing examples; at least {EXAMPLES_MIN} are needed"
            )
        sheet, count = numbered_fact_sheet(run.ledger)
        text = writer_packet(run.run_id, sheet, claim_types, [reports[e] for e in examples], shown)
        texts[run.run_id] = text
        hit = _first_hit(_INSTRUMENT, [text])
        if hit is not None:
            flagged.append({"run_id": run.run_id, "rule": hit[0], "fragment": hit[1]})
        entries.append(
            {
                "run_id": run.run_id,
                "file": f"{run.run_id}.md",
                "sha256": sha256_bytes(text.encode("utf-8")),
                "fact_lines": count,
                "fact_sheet_sha256": sha256_bytes(sheet.encode("utf-8")),
                "ledger_sha256": sha256_file(run.path / "ledger.jsonl"),
                "examples": examples,
            }
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    for run_id, text in texts.items():
        (out_dir / f"{run_id}.md").write_bytes(text.encode("utf-8"))
    index = {
        "schema": "receipts.e0.writer_packets/1",
        "runs_dir": display_path(root, runs_dir),
        "claim_types_sha256": sha256_file(root / CLAIM_TYPES_DOC),
        "seed": SPLIT_SEED,
        "packets": entries,
        "flagged": flagged,
        "provenance": provenance(root, command),
    }
    write_json(out_dir / "index.json", index)
    return index


# ---------------------------------------------------------------- 4 and 5. checks


def is_id(value: object) -> bool:
    """True for an id: letters, digits, ``.``, ``_``, ``-``; at most 128; no leading mark."""
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def claim_span(report: str, text: str, occurrence: int = 1) -> tuple[int, int] | None:
    """Span of the ``occurrence``-th non-overlapping occurrence of ``text`` in ``report``.

    Returns None when ``text`` is empty or occurs fewer than ``occurrence`` times
    (occurrences are counted like ``str.count``).
    """
    if not text or occurrence < 1:
        return None
    start, position = -1, 0
    for _ in range(occurrence):
        start = report.find(text, position)
        if start < 0:
            return None
        position = start + len(text)
    return (start, start + len(text))


def _key_problems(prefix: str, data: Mapping[str, Any], allowed: frozenset[str]) -> list[str]:
    required = allowed - {"occurrence"}
    unknown = [f"{prefix}unknown key {k!r}" for k in sorted(set(data) - allowed)]
    return unknown + [f"{prefix}missing key {k!r}" for k in sorted(required - set(data))]


def _label_problems(tag: str, item: Mapping[str, Any], limit: int | None) -> list[str]:
    problems: list[str] = []
    ctype, truth = item.get("type"), item.get("truth")
    if "type" in item and not (isinstance(ctype, str) and ctype in GOLD_CLAIM_TYPES):
        problems.append(f"{tag}: type {ctype!r} is not one of the claim types")
    if "truth" in item and not (isinstance(truth, str) and truth in VERDICTS):
        problems.append(f"{tag}: truth must be supported, contradicted, or unverifiable")
    if "evidence_lines" in item:
        lines = item["evidence_lines"]
        if not isinstance(lines, list) or not all(_is_int(n) for n in lines):
            problems.append(f"{tag}: evidence_lines must be a list of line numbers")
        else:
            bad = [n for n in lines if n < 1 or (limit is not None and n > limit)]
            if bad:
                known = f"L1 to L{limit}" if limit is not None else "numbered from L1"
                listed = ", ".join(map(str, bad))
                problems.append(f"{tag}: evidence line(s) {listed} not in the fact sheet ({known})")
    return problems


def _claim_problems(
    claim: object, index: int, report: str | None, limit: int | None, seen: set[str]
) -> list[str]:
    if not isinstance(claim, dict):
        return [f"claim {index}: not a JSON object"]
    cid = claim.get("claim_id")
    tag = f"claim {cid}" if is_id(cid) else f"claim {index}"
    problems = _key_problems(f"{tag}: ", claim, _CLAIM_KEYS)
    if "claim_id" in claim:
        if not is_id(cid):
            problems.append(f"{tag}: claim_id must be an id such as g1")
        elif cid in seen:
            problems.append(f"{tag}: claim_id is used twice")
        else:
            seen.add(str(cid))
    occurrence = claim.get("occurrence", 1)
    if not _is_int(occurrence) or occurrence < 1:
        problems.append(f"{tag}: occurrence must be a whole number of at least 1")
        occurrence = None
    text = claim.get("text")
    if "text" in claim:
        if not isinstance(text, str) or not text:
            problems.append(f"{tag}: text must be a non-empty string")
        elif report is not None and occurrence is not None:
            found = report.count(text)
            if found == 0:
                problems.append(f"{tag}: text is not a verbatim part of the report")
            elif found < occurrence:
                problems.append(
                    f"{tag}: text occurs {found} time(s) in the report, so occurrence "
                    f"{occurrence} does not exist"
                )
    return problems + _label_problems(tag, claim, limit)


def raw_problems(data: object, fact_lines: Mapping[str, int] | None = None) -> list[str]:
    """Problems with one writer output (empty when it is valid).

    ``fact_lines`` maps each run id with a writer packet to its number of fact-sheet
    lines; when given, the run must have a packet and evidence lines must exist in it.
    """
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    problems = _key_problems("", data, _RAW_KEYS)
    for key in ("report_id", "run_id", "writer"):
        if key in data and not is_id(data[key]):
            problems.append(f"{key} must be an id (letters, digits, '.', '_', '-'; at most 128)")
    limit: int | None = None
    run_id = data.get("run_id")
    if fact_lines is not None and is_id(run_id):
        if run_id in fact_lines:
            limit = fact_lines[str(run_id)]
        else:
            problems.append(f"run_id {run_id!r} has no writer packet")
    report = data.get("report")
    if "report" in data and (not isinstance(report, str) or not report.strip()):
        problems.append("report must be a non-empty string")
    claims = data.get("claims")
    if "claims" in data and (not isinstance(claims, list) or not claims):
        problems.append("claims must be a non-empty list")
    if isinstance(claims, list):
        seen: set[str] = set()
        text = report if isinstance(report, str) else None
        for index, claim in enumerate(claims, start=1):
            problems.extend(_claim_problems(claim, index, text, limit, seen))
    return problems


def adjudication_problems(
    data: object, claim_ids: Sequence[str] | None, fact_lines: int | None = None
) -> list[str]:
    """Problems with one adjudicator output (empty when it is valid).

    With ``claim_ids`` (the report's gold claim ids), every one must be labeled exactly
    once and no other id may appear; with ``fact_lines``, evidence lines must exist.
    """
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    problems = _key_problems("", data, _ADJ_KEYS)
    for key in ("report_id", "adjudicator"):
        if key in data and not is_id(data[key]):
            problems.append(f"{key} must be an id (letters, digits, '.', '_', '-'; at most 128)")
    labels = data.get("labels")
    if not isinstance(labels, list):
        return [*problems, "labels must be a list"]
    labeled: Counter[str] = Counter()
    known = None if claim_ids is None else set(claim_ids)
    for index, label in enumerate(labels, start=1):
        if not isinstance(label, dict):
            problems.append(f"label {index}: not a JSON object")
            continue
        cid = label.get("claim_id")
        tag = f"label {cid}" if is_id(cid) else f"label {index}"
        problems.extend(_key_problems(f"{tag}: ", label, _LABEL_KEYS))
        if is_id(cid):
            labeled[str(cid)] += 1
            if known is not None and cid not in known:
                problems.append(f"{tag}: the report has no claim {cid!r}")
        elif "claim_id" in label:
            problems.append(f"{tag}: claim_id must be an id such as g1")
        problems.extend(_label_problems(tag, label, fact_lines))
    problems.extend(f"claim {c} is labeled {n} times" for c, n in labeled.items() if n > 1)
    if claim_ids is not None:
        missing = [c for c in claim_ids if labeled[c] == 0]
        if missing:
            problems.append("claims not labeled: " + ", ".join(missing))
    return problems


def _index(path: Path, key: str, schema: str) -> list[Mapping[str, Any]]:
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema") != schema:
        raise E0Error(f"{path} is not a {schema} index")
    entries = data.get(key)
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise E0Error(f"{path} lists no {key}")
    return entries


def writer_index(packets_dir: Path) -> list[Mapping[str, Any]]:
    """The packet entries of ``<packets_dir>/index.json`` (from :func:`write_writer_packets`)."""
    return _index(packets_dir / "index.json", "packets", "receipts.e0.writer_packets/1")


def adjudication_index(packets_dir: Path) -> list[Mapping[str, Any]]:
    """The report entries of an adjudication packet index."""
    return _index(packets_dir / "index.json", "reports", "receipts.e0.adjudication_packets/1")


def _duplicate(
    seen: dict[str, Path], key: object, path: Path, name: str = "report_id"
) -> str | None:
    if not isinstance(key, str):
        return None
    if key in seen:
        return f"{path}: {name} {key!r} is also used by {seen[key]}"
    seen[key] = path
    return None


def check_raw_files(paths: Sequence[Path], packets_dir: Path) -> list[str]:
    """One line per problem in the writer outputs ``paths`` (``check-raw``)."""
    fact_counts = {str(e["run_id"]): int(e["fact_lines"]) for e in writer_index(packets_dir)}
    problems: list[str] = []
    seen: dict[str, Path] = {}
    for path in paths:
        data, error = read_json(path)
        if error is not None:
            problems.append(f"{path}: {error}")
            continue
        problems.extend(f"{path}: {p}" for p in raw_problems(data, fact_counts))
        if isinstance(data, dict):
            clash = _duplicate(seen, data.get("report_id"), path)
            if clash is not None:
                problems.append(clash)
    return problems


def check_adjudication_files(paths: Sequence[Path], packets_dir: Path) -> list[str]:
    """One line per problem in the adjudicator outputs ``paths`` (``check-adjudication``)."""
    entries = {str(e["report_id"]): e for e in adjudication_index(packets_dir)}
    problems: list[str] = []
    seen: dict[str, Path] = {}
    for path in paths:
        data, error = read_json(path)
        if error is not None:
            problems.append(f"{path}: {error}")
            continue
        report_id = data.get("report_id") if isinstance(data, dict) else None
        entry = entries.get(report_id) if isinstance(report_id, str) else None
        if isinstance(report_id, str) and entry is None:
            problems.append(f"{path}: report_id {report_id!r} has no adjudication packet")
        claim_ids = None if entry is None else [str(c) for c in entry["claim_ids"]]
        limit = None if entry is None else int(entry["fact_lines"])
        problems.extend(f"{path}: {p}" for p in adjudication_problems(data, claim_ids, limit))
        clash = _duplicate(seen, report_id, path)
        if clash is not None:
            problems.append(clash)
    return problems


def _read_outputs(
    directory: Path, problems_of: Callable[[object], list[str]], what: str, key: str
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every ``<directory>/*.json`` by its ``key``, with its path; E0Error on any problem."""
    if not directory.is_dir():
        raise E0Error(f"{directory} is not a directory")
    loaded: dict[str, tuple[Path, dict[str, Any]]] = {}
    problems: list[str] = []
    for path in sorted(directory.glob("*.json")):
        data, error = read_json(path)
        found = [error] if error is not None else problems_of(data)
        if found:
            problems.extend(f"{path.name}: {p}" for p in found)
            continue
        if data[key] in loaded:
            problems.append(f"{path.name}: {key} {data[key]!r} appears twice")
            continue
        loaded[str(data[key])] = (path, data)
    if problems:
        shown = "; ".join(problems[:10]) + ("; ..." if len(problems) > 10 else "")
        raise E0Error(f"{what} in {directory} have problems: {shown}")
    if not loaded:
        raise E0Error(f"no {what} in {directory}")
    return loaded


def _load_outputs(
    directory: Path, problems_of: Callable[[object], list[str]], what: str, key: str
) -> dict[str, dict[str, Any]]:
    """:func:`_read_outputs` without the paths."""
    outputs = _read_outputs(directory, problems_of, what, key)
    return {name: data for name, (_, data) in outputs.items()}


def load_raw_dir(
    raw_dir: Path, fact_counts: Mapping[str, int] | None = None
) -> dict[str, dict[str, Any]]:
    """Every writer output ``<raw_dir>/*.json`` by report id; E0Error on any problem."""
    return _load_outputs(
        raw_dir, lambda data: raw_problems(data, fact_counts), "writer outputs", "report_id"
    )


def adjudication_packet(
    report_id: str,
    run_id: str,
    fact_sheet: str,
    claim_types: str,
    report: str,
    claims: Sequence[Mapping[str, Any]],
    packets_dir: str,
) -> str:
    """The markdown packet one blind adjudicator works from (no writer labels)."""
    template = {
        "report_id": report_id,
        "adjudicator": "<your adjudicator id from your task message>",
        "labels": [
            {"claim_id": "g1", "type": "tests_pass", "truth": "contradicted", "evidence_lines": [7]}
        ],
    }
    parts = [
        f"# E0 adjudication packet: report {report_id}\n",
        "This packet holds everything you need: the fact sheet of a real run, a final "
        "report written for that run, and the claims in that report. For each claim, "
        "decide its type and whether the fact sheet supports it, contradicts it, or does "
        "not settle it.\n",
        "## Rules\n",
        "1. Use only this packet. Do not open, search, or run anything else in the "
        "repository, except the check command in the Output section. Never read or search "
        "`src/`, never import a receipts module, and never open another writer's or "
        "adjudicator's files. Any such access voids your labels.\n"
        "2. Label every claim in the list exactly once, from the fact sheet and the "
        "claim's words (find them in the report by their text and occurrence).\n"
        "3. `type`: one of the types in the claim-type table. `truth`: `supported`, "
        "`contradicted`, or `unverifiable`, judged only from the fact sheet and the "
        'table\'s "True when the record shows" column. `evidence_lines`: the numbers of '
        "the fact-sheet lines your truth rests on (12 for line L12); leave it empty only "
        "when no line bears on the claim.\n",
        "## Output\n",
        "Write one JSON file in exactly this format (the label shown only illustrates the "
        "fields). Create it with your file-writing tool, not through a shell command: shell "
        "commands that name other parts of the repository are flagged.\n",
        fenced(json.dumps(template, indent=2), "json"),
        "Then run this check and fix every problem it prints until it reports none:\n",
        fenced(
            f"uv run --no-sync python tools/e0.py check-adjudication --packets {packets_dir} "
            "<your file>"
        ),
        "## Claims to label\n",
        fenced(json.dumps(list(claims), indent=2), "json"),
        "## The report\n",
        fenced(report),
        f"## Fact sheet of run {run_id}\n",
        fenced(fact_sheet),
        "## Claim types\n",
        claim_types,
    ]
    return "\n".join(parts)


def write_adjudication_packets(
    root: Path, runs_dir: Path, raw_dir: Path, packets_dir: Path, out_dir: Path, *, command: str
) -> dict[str, Any]:
    """Write one adjudication packet per writer output, and ``<out_dir>/index.json``.

    The fact sheet is rebuilt from the run's ledger and must hash to what the writer saw
    (``fact_sheet_sha256`` in the writer packet index), so line numbers mean the same.
    """
    by_run = {str(e["run_id"]): e for e in writer_index(packets_dir)}
    raws = load_raw_dir(raw_dir, {run: int(e["fact_lines"]) for run, e in by_run.items()})
    claim_types = claim_types_text(root)
    shown = display_path(root, out_dir)
    entries: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    for report_id, raw in sorted(raws.items()):
        run_id = str(raw["run_id"])
        try:
            ledger = Ledger.load(runs_dir / run_id / "ledger.jsonl")
        except (OSError, ValueError) as exc:
            raise E0Error(f"run {run_id}: cannot load its ledger ({exc})") from exc
        sheet, count = numbered_fact_sheet(ledger)
        if sha256_bytes(sheet.encode("utf-8")) != by_run[run_id].get("fact_sheet_sha256"):
            raise E0Error(f"run {run_id}: its fact sheet differs from the one the writer saw")
        claims = [
            {"claim_id": c["claim_id"], "text": c["text"], "occurrence": c.get("occurrence", 1)}
            for c in raw["claims"]
        ]
        text = adjudication_packet(
            report_id, run_id, sheet, claim_types, str(raw["report"]), claims, shown
        )
        texts[report_id] = text
        entries.append(
            {
                "report_id": report_id,
                "run_id": run_id,
                "file": f"{report_id}.md",
                "sha256": sha256_bytes(text.encode("utf-8")),
                "claim_ids": [c["claim_id"] for c in claims],
                "fact_lines": count,
            }
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    for report_id, text in texts.items():
        (out_dir / f"{report_id}.md").write_bytes(text.encode("utf-8"))
    index = {
        "schema": "receipts.e0.adjudication_packets/1",
        "writer_packets": display_path(root, packets_dir),
        "reports": entries,
        "provenance": provenance(root, command),
    }
    write_json(out_dir / "index.json", index)
    return index


# ---------------------------------------------------------------- 6. blindness


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _access_strings(value: object, keys: frozenset[str]) -> Iterator[str]:
    """The strings under the access fields ``keys`` of a tool-call input, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                yield from _strings(item)
            else:
                yield from _access_strings(item, keys)
    elif isinstance(value, list):
        for item in value:
            yield from _access_strings(item, keys)


def _blocks(value: object, kind: str) -> Iterator[Mapping[str, Any]]:
    """Every dict whose ``type`` is ``kind`` inside ``value``, outermost first."""
    if isinstance(value, dict):
        if value.get("type") == kind:
            yield value
        for item in value.values():
            yield from _blocks(item, kind)
    elif isinstance(value, list):
        for item in value:
            yield from _blocks(item, kind)


def transcript_records(data: bytes) -> tuple[list[dict[str, Any]], int]:
    """The JSON object on each line of a JSONL transcript, and how many lines hold none.

    Lines are split on ``\\n`` only: JSON writers leave U+2028, U+2029, and U+0085
    unescaped inside strings, so splitting on every Unicode line boundary
    (:meth:`str.splitlines`) would cut a record in two and hide its tool calls. A line
    that is not UTF-8, not JSON, or not a JSON object counts as unparsed; blank lines do
    not count.
    """
    records: list[dict[str, Any]] = []
    unparsed = 0
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            unparsed += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            unparsed += 1
    return records, unparsed


def _tool_calls(record: Mapping[str, Any]) -> Iterator[tuple[str, str, object]]:
    """``(tool use id, tool name, input)`` of every tool call one record holds.

    Claude Code keeps a call's input in its ``tool_use`` block and a copy of it under
    ``wireToolInputs``; both are read, so a call is scanned even when one is elided.
    """
    for use in _blocks(record, "tool_use"):
        yield str(use.get("id") or ""), str(use.get("name") or ""), use.get("input")
    wire = record.get("wireToolInputs")
    if isinstance(wire, dict):
        for use_id, value in wire.items():
            yield str(use_id), "", value


def _tool_results(record: Mapping[str, Any]) -> Iterator[tuple[str, object]]:
    """``(tool use id, content)`` of every tool result one record holds.

    The result is in a ``tool_result`` block and again under ``toolUseResult``, which
    belongs to the record's only ``tool_result`` block (id "" when there are several).
    """
    ids: list[str] = []
    for block in _blocks(record, "tool_result"):
        use_id = str(block.get("tool_use_id") or "")
        ids.append(use_id)
        yield use_id, block.get("content")
    if "toolUseResult" in record:
        yield (ids[0] if len(ids) == 1 else ""), record["toolUseResult"]


def _first_hit(
    rules: Sequence[tuple[str, re.Pattern[str]]], texts: Iterable[str], *, allow: bool = False
) -> tuple[str, str] | None:
    """``(rule name, fragment)`` of the first text a rule matches, or None.

    With ``allow``, the access every writer needs (the check commands and the claim-type
    page) is blanked out before matching.
    """
    for text in texts:
        scanned = _ALLOWED_ACCESS.sub(lambda m: " " * len(m.group()), text) if allow else text
        for name, pattern in rules:
            match = pattern.search(scanned)
            if match is not None:
                return name, _fragment(text, match)
    return None


def scan_transcript(path: Path) -> dict[str, Any]:
    """Blindness check of one subagent transcript (Claude Code JSONL).

    Only the transcript's tool calls and tool results are read; its task message, system
    text, and the subagent's own prose are not. Returns:

    - ``violations``: one per tool call whose input (any field) and one per tool result
      whose content matches an INSTRUMENT_RULES rule, with the tool name, ``where``
      (``input`` or ``result``), the rule, and a fragment of at most 40 characters on
      either side of the match;
    - ``reviews``: one per tool call without a violation whose access fields match a
      REVIEW_RULES rule (same fields, and ``cleared`` None until a person clears it);
    - ``names``: the writer, adjudicator, and labeler ids its tool calls declare (a
      ``"writer": "<id>"``, ``"adjudicator": "<id>"``, or ``"labeler": "<id>"`` pair, as
      in the output it wrote; ids it only read in a tool result are not its own);
    - ``unparsed_lines``: lines that are not JSON objects (:func:`transcript_records`);
    - the file name and its SHA-256. Nothing else from the transcript is kept.
    """
    data = path.read_bytes()
    records, unparsed = transcript_records(data)
    tools: dict[str, str] = {}
    calls: dict[str, list[object]] = {}
    results: dict[str, list[object]] = {}
    order: list[tuple[str, str]] = []
    names: set[str] = set()
    for number, record in enumerate(records):
        for index, (use_id, name, value) in enumerate(_tool_calls(record)):
            key = use_id or f"line {number} call {index}"
            if name:
                tools.setdefault(key, name)
            if key not in calls:
                calls[key] = []
                order.append(("input", key))
            calls[key].append(value)
            for text in _strings(value):
                names.update(match.group(2) for match in _DECLARED_NAME.finditer(text))
        for index, (use_id, value) in enumerate(_tool_results(record)):
            key = use_id or f"line {number} result {index}"
            if key not in results:
                results[key] = []
                order.append(("result", key))
            results[key].append(value)
    violations: list[dict[str, str]] = []
    reviews: list[dict[str, Any]] = []
    for where, key in order:
        tool = tools.get(key, "")
        values = calls[key] if where == "input" else results[key]
        hit = _first_hit(_INSTRUMENT, (text for value in values for text in _strings(value)))
        if hit is not None:
            violations.append({"tool": tool, "where": where, "rule": hit[0], "fragment": hit[1]})
            continue
        if where == "input":
            keys = _GLOB_ACCESS_KEYS if tool == "Glob" else ACCESS_KEYS
            texts = (text for value in values for text in _access_strings(value, keys))
            hit = _first_hit(_REVIEW, texts, allow=True)
            if hit is not None:
                reviews.append({"tool": tool, "rule": hit[0], "fragment": hit[1], "cleared": None})
    return {
        "file": path.name,
        "sha256": sha256_bytes(data),
        "violations": violations,
        "reviews": reviews,
        "names": sorted(names),
        "unparsed_lines": unparsed,
    }


def _fragment(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - _FRAGMENT_CONTEXT)
    return text[start : match.end() + _FRAGMENT_CONTEXT]


def voids(scan: Mapping[str, Any]) -> bool:
    """True when a scanned transcript voids the ids it declares.

    It does when it has a violation, a review entry no person cleared, or a line that is
    not a JSON object (so part of it could not be checked).
    """
    reviews = scan.get("reviews") or []
    return (
        bool(scan.get("violations"))
        or bool(scan.get("unparsed_lines"))
        or any(not isinstance(r, dict) or r.get("cleared") is None for r in reviews)
    )


def load_clearances(path: Path) -> list[dict[str, str]]:
    """The review entries a person cleared, from ``path``.

    The file is ``{"clearances": [{"file", "sha256", "fragment", "by", "reason"}]}``:
    the transcript's file name and SHA-256, the review fragment exactly as listed in
    ``blindness.json``, who looked at it, and why it does not reach the instrument.
    """
    data = load_json(path)
    entries = data.get("clearances") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise E0Error(f"{path} lists no clearances")
    for number, entry in enumerate(entries, start=1):
        if not (
            isinstance(entry, dict)
            and set(entry) == _CLEARANCE_KEYS
            and all(isinstance(v, str) and v.strip() for v in entry.values())
        ):
            raise E0Error(
                f"{path}: clearance {number} needs a non-empty file, sha256, fragment, by, "
                "and reason, and nothing else"
            )
    return entries


def apply_clearances(
    scans: Sequence[Mapping[str, Any]], clearances: Sequence[Mapping[str, str]], where: str
) -> None:
    """Mark the review entries each clearance names as cleared (by whom, and why).

    A clearance must match a review entry of a scanned transcript (same file, SHA-256,
    and fragment); one that matches nothing (a changed transcript, a violation, a typo)
    is refused, so a clearance can never cover a violation.
    """
    for number, clearance in enumerate(clearances, start=1):
        matched = 0
        for scan in scans:
            if (scan["file"], scan["sha256"]) != (clearance["file"], clearance["sha256"]):
                continue
            for review in scan["reviews"]:
                if review["fragment"] == clearance["fragment"]:
                    review["cleared"] = {"by": clearance["by"], "reason": clearance["reason"]}
                    matched += 1
        if not matched:
            raise E0Error(
                f"{where}: clearance {number} matches no review entry of a scanned transcript "
                "(same file, sha256, and fragment)"
            )


def transcript_files(paths: Iterable[Path]) -> list[Path]:
    """The ``*.jsonl`` files under each directory in ``paths`` (and each file itself)."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.jsonl")))
        elif path.is_file():
            files.append(path)
        else:
            raise E0Error(f"{path} does not exist")
    return files


def _scan_all(
    root: Path, paths: Sequence[Path], clearances: Path | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Every transcript under ``paths`` scanned, with the ``clearances`` file applied.

    Returns the scans and the record of the clearances file (its path, SHA-256, and
    number of entries), None without one.
    """
    files = transcript_files(paths)
    if not files:
        raise E0Error("no transcript files to scan")
    scans = [scan_transcript(path) for path in files]
    if clearances is None:
        return scans, None
    entries = load_clearances(clearances)
    shown = display_path(root, clearances)
    apply_clearances(scans, entries, shown)
    return scans, {"path": shown, "sha256": sha256_file(clearances), "count": len(entries)}


def blindness_artifact(
    root: Path, paths: Sequence[Path], *, command: str, clearances: Path | None = None
) -> dict[str, Any]:
    """``artifacts/e0/blindness.json``: per transcript, its hash, violations, and reviews.

    ``transcripts`` holds one record per transcript (:func:`scan_transcript`); the lists
    sum them up. ``declared`` lists every id any record declares; ``voided`` every id
    declared by a record that :func:`voids`; ``unattributed`` the records that void but
    declare no id, and ``unscannable`` those with lines that are not JSON objects. Merge
    and counts read the ids from the records and refuse a list that differs from them, a
    non-empty ``unattributed`` or ``unscannable``, and a writer, adjudicator, or labeler
    no record declares (:func:`blindness_ids`). ``clearances`` is a file of review
    entries a person cleared (:func:`load_clearances`); a cleared entry no longer voids.
    """
    scans, cleared = _scan_all(root, paths, clearances)
    voiding = [scan for scan in scans if voids(scan)]
    return {
        "schema": _BLINDNESS_SCHEMA,
        "forbidden": list(FORBIDDEN_REFERENCES),
        "rules": {"violation": dict(INSTRUMENT_RULES), "review": dict(REVIEW_RULES)},
        "transcripts": scans,
        "declared": sorted({name for scan in scans for name in scan["names"]}),
        "voided": sorted({name for scan in voiding for name in scan["names"]}),
        "unattributed": [scan["file"] for scan in voiding if not scan["names"]],
        "unscannable": [scan["file"] for scan in scans if scan["unparsed_lines"]],
        "clearances": cleared,
        "provenance": provenance(root, command),
    }


# ---------------------------------------------------------------- 6. reading a blindness file

_RESCAN = "scan the transcripts again with tools/e0.py blindness"


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_review(entry: object) -> bool:
    """True for a review entry as :func:`scan_transcript` writes it, cleared or not."""
    if not (isinstance(entry, dict) and set(entry) == _REVIEW_KEYS):
        return False
    if not all(isinstance(entry[key], str) for key in ("tool", "rule", "fragment")):
        return False
    cleared = entry["cleared"]
    return cleared is None or (
        isinstance(cleared, dict)
        and set(cleared) == _CLEARED_KEYS
        and all(_is_text(value) for value in cleared.values())
    )


def _scan_record_problems(record: object, number: int) -> list[str]:
    """Problems with transcript record ``number`` of a blindness file.

    Empty when it has the shape :func:`scan_transcript` gives it, with each review entry
    cleared or not (:func:`apply_clearances`).
    """
    tag = f"transcript {number}"
    if not isinstance(record, dict):
        return [f"{tag}: not a JSON object"]
    problems = _key_problems(f"{tag}: ", record, _SCAN_KEYS)
    if "file" in record and not _is_text(record["file"]):
        problems.append(f"{tag}: file must be a non-empty string")
    if "sha256" in record and not _is_sha256(record["sha256"]):
        problems.append(f"{tag}: sha256 must be 64 lowercase hex digits")
    names = record.get("names")
    if "names" in record and not (isinstance(names, list) and all(is_id(n) for n in names)):
        problems.append(f"{tag}: names must be a list of ids")
    for key in ("violations", "reviews"):
        if key in record and not isinstance(record[key], list):
            problems.append(f"{tag}: {key} must be a list")
    lines = record.get("unparsed_lines", 0)
    if not (_is_int(lines) and lines >= 0):
        problems.append(f"{tag}: unparsed_lines must be a whole number")
    reviews = record.get("reviews")
    if isinstance(reviews, list):
        problems.extend(
            f"{tag}: review {index} needs a tool, a rule, a fragment, and cleared (null, or "
            "by and reason)"
            for index, entry in enumerate(reviews, start=1)
            if not _is_review(entry)
        )
    return problems


def _list_problems(blindness: Mapping[str, Any], key: str, given: set[str]) -> list[str]:
    """How the ``key`` list of a blindness file differs from ``given``, what its records give."""
    listed = blindness.get(key)
    if not isinstance(listed, list) or not all(isinstance(item, str) for item in listed):
        return [f"it has no {key} list of names"]
    problems: list[str] = []
    extra, missing = sorted(set(listed) - given), sorted(given - set(listed))
    if extra:
        problems.append(f"its {key} list has {', '.join(extra)}, which its records do not")
    if missing:
        problems.append(f"its records have {', '.join(missing)}, which its {key} list does not")
    return problems


def _clearances_record_problems(record: object, cleared: bool) -> list[str]:
    """Problems with a blindness file's clearances record, given whether a review entry is
    marked cleared: one is exactly when the record counts at least one clearance."""
    if record is not None and not (
        isinstance(record, dict)
        and set(record) == _CLEARANCES_RECORD_KEYS
        and _is_text(record["path"])
        and _is_sha256(record["sha256"])
        and _is_int(record["count"])
        and record["count"] >= 0
    ):
        return ["its clearances record is not a path, a SHA-256, and a count"]
    count = record["count"] if isinstance(record, dict) else 0
    if cleared != (count > 0):
        return ["its review entries marked cleared do not match its clearances record"]
    return []


def blindness_ids(blindness: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """``(declared, voided)``: the labeler, writer, and adjudicator ids of a blindness file.

    Both come from its transcript records (``transcripts``, as :func:`blindness_artifact`
    writes them): ``declared`` holds every id a record declares, and ``voided`` every id
    declared by a record that :func:`voids`. The summary lists must be what the records
    give, so an edited list can neither clear nor un-void anyone. The records are taken
    as the scan wrote them; :func:`_check_rescan` checks them against a new scan of the
    transcripts. Raises E0Error when the file is not a blindness artifact of this schema
    or lists no transcript; when a record is not a transcript scan; when its
    ``declared``, ``voided``, ``unattributed``, or ``unscannable`` list, or its
    clearances record, is not what its records give (an edited or damaged file); when a
    transcript could not be read in full; and when one voids but declares no id.
    """
    if blindness.get("schema") != _BLINDNESS_SCHEMA:
        raise E0Error(f"the blindness file is not a {_BLINDNESS_SCHEMA} artifact")
    records = blindness.get("transcripts")
    if not isinstance(records, list) or not records:
        raise E0Error(
            "the blindness file lists no scanned transcript; scan the subagents' transcripts "
            "with tools/e0.py blindness"
        )
    problems = [
        problem
        for number, record in enumerate(records, start=1)
        for problem in _scan_record_problems(record, number)
    ]
    if problems:
        shown = "; ".join(problems[:10]) + ("; ..." if len(problems) > 10 else "")
        raise E0Error(
            f"the blindness file holds records that are not transcript scans ({shown}); " + _RESCAN
        )
    voiding = [record for record in records if voids(record)]
    derived = {
        "declared": {str(name) for record in records for name in record["names"]},
        "voided": {str(name) for record in voiding for name in record["names"]},
        "unattributed": {str(record["file"]) for record in voiding if not record["names"]},
        "unscannable": {str(record["file"]) for record in records if record["unparsed_lines"]},
    }
    mismatch = [p for key, given in derived.items() for p in _list_problems(blindness, key, given)]
    cleared = any(entry["cleared"] is not None for record in records for entry in record["reviews"])
    mismatch += _clearances_record_problems(blindness.get("clearances"), cleared)
    if mismatch:
        raise E0Error(
            "the blindness file does not match its transcript records ("
            + "; ".join(mismatch)
            + "); it was edited or is damaged: "
            + _RESCAN
        )
    if derived["unscannable"]:
        raise E0Error(
            "the blindness scan could not read every line of some transcripts (lines that "
            "are not JSON objects: " + ", ".join(sorted(derived["unscannable"])) + "); scan "
            "them in full"
        )
    if derived["unattributed"]:
        raise E0Error(
            "blindness violations or uncleared reviews in transcripts that declare no writer, "
            "adjudicator, or labeler id: " + ", ".join(sorted(derived["unattributed"]))
        )
    return derived["declared"], derived["voided"]


def _check_rescan(root: Path, blindness: Mapping[str, Any], paths: Sequence[Path]) -> None:
    """Refuse unless scanning the transcripts ``paths`` again gives the file ``blindness``.

    ``blindness`` must pass :func:`blindness_ids` first. The new scan applies the
    clearances file the blindness file records, which must still have the recorded
    SHA-256, and must give the same transcript records, in any order, and the same
    clearances record. Raises E0Error naming each transcript whose record the new scan
    gives differently, each record with no transcript of its file name and SHA-256 under
    ``paths``, and each transcript under ``paths`` the file does not record.
    """
    record = blindness.get("clearances")
    clearances: Path | None = None
    if isinstance(record, dict):
        clearances = root / str(record["path"])
        if not clearances.is_file() or sha256_file(clearances) != record["sha256"]:
            raise E0Error(
                f"the clearances file {record['path']} that the blindness file records is "
                f"missing or changed since the scan; {_RESCAN}"
            )
    scans, cleared = _scan_all(root, paths, clearances)

    def keyed(records: Iterable[Mapping[str, Any]]) -> Counter[tuple[str, str, str]]:
        """Each record by its file name, SHA-256, and text (a record may appear twice)."""
        return Counter((str(r["file"]), str(r["sha256"]), dump_json(r)) for r in records)

    lost = keyed(blindness["transcripts"]) - keyed(scans)
    found = keyed(scans) - keyed(blindness["transcripts"])
    lost_keys, found_keys = {key[:2] for key in lost}, {key[:2] for key in found}
    parts: list[str] = []
    for files, text in (
        (lost_keys & found_keys, "a new scan gives other entries for "),
        (lost_keys - found_keys, "no transcript has the file name and SHA-256 of "),
        (found_keys - lost_keys, "it does not record "),
    ):
        if files:
            parts.append(text + ", ".join(sorted(file for file, _ in files)))
    if cleared != record:
        parts.append("its clearances record is not the new scan's")
    if parts:
        raise E0Error(
            "the blindness file is not what a new scan of the transcripts gives ("
            + "; ".join(parts)
            + "); scan them again with tools/e0.py blindness"
        )


def _load_blindness(
    root: Path, path: Path, agents: Sequence[Path] | None
) -> tuple[dict[str, Any], set[str], set[str], dict[str, Any]]:
    """The blindness file at ``path``, its declared and voided ids, and its record.

    The ids are :func:`blindness_ids`. With ``agents`` (the transcripts it scanned), the
    file must also be what a new scan of them gives (:func:`_check_rescan`). The record
    is the file's path and SHA-256, and ``rescanned``: whether that new scan ran.
    """
    blindness = load_json(path)
    if not isinstance(blindness, dict):
        raise E0Error(f"{path} is not a blindness artifact")
    declared, voided = blindness_ids(blindness)
    if agents is not None:
        _check_rescan(root, blindness, agents)
    record = {
        "path": display_path(root, path),
        "sha256": sha256_file(path),
        "rescanned": agents is not None,
    }
    return blindness, declared, voided, record


# ---------------------------------------------------------------- 7. merge


def _drop_reason(same_type: bool, same_truth: bool) -> str:
    if not same_type and not same_truth:
        return "type_and_truth"
    return "type" if not same_type else "truth"


def merge_reports(
    raw_dir: Path, adjudication_dir: Path, blindness: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Merge writer outputs with adjudications into gold, ignored, and dropped claims.

    A writer claim is gold only when the adjudicator's type and truth both equal the
    writer's. Otherwise it is dropped from the gold set, counted by the writer's type and
    the reason (``type``, ``truth``, or ``type_and_truth``), and kept as an ignored claim
    with every type either labeler gave it. Reports whose writer or adjudicator the
    blindness file voids are excluded; the declared and voided ids come from its
    transcript records (:func:`blindness_ids`). Raises E0Error on invalid or missing
    files, on a report adjudicated by its own writer, on a blindness file that
    :func:`blindness_ids` refuses, and on a writer or adjudicator that no transcript
    record declares.
    """
    raws = load_raw_dir(raw_dir)

    def check(data: object) -> list[str]:
        report_id = data.get("report_id") if isinstance(data, dict) else None
        raw = raws.get(report_id) if isinstance(report_id, str) else None
        if raw is None:
            return [f"no writer output has report_id {report_id!r}"]
        return adjudication_problems(data, [str(c["claim_id"]) for c in raw["claims"]])

    adjudications = _load_outputs(adjudication_dir, check, "adjudications", "report_id")
    missing = sorted(set(raws) - set(adjudications))
    if missing:
        raise E0Error("reports with no adjudication: " + ", ".join(missing))
    voided: set[str] = set()
    if blindness is not None:
        declared, voided = blindness_ids(blindness)
        people = {str(r["writer"]) for r in raws.values()}
        people |= {str(a["adjudicator"]) for a in adjudications.values()}
        unscanned = sorted(people - declared)
        if unscanned:
            raise E0Error(
                "no scanned transcript declares these writers or adjudicators: "
                + ", ".join(unscanned)
            )
    reports: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    drops: dict[str, Counter[str]] = {}
    kept: Counter[str] = Counter()
    for report_id, raw in sorted(raws.items()):
        adjudication = adjudications[report_id]
        writer, adjudicator = str(raw["writer"]), str(adjudication["adjudicator"])
        if writer == adjudicator:
            raise E0Error(f"report {report_id} was adjudicated by its own writer {writer}")
        if writer in voided or adjudicator in voided:
            who = "writer" if writer in voided else "adjudicator"
            excluded.append(
                {
                    "report_id": report_id,
                    "writer": writer,
                    "adjudicator": adjudicator,
                    "reason": f"{who} voided by the blindness check",
                    "claims": len(raw["claims"]),
                }
            )
            continue
        labels = {str(label["claim_id"]): label for label in adjudication["labels"]}
        gold: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []
        for claim in raw["claims"]:
            label = labels[str(claim["claim_id"])]
            occurrence = int(claim.get("occurrence", 1))
            span = claim_span(str(raw["report"]), str(claim["text"]), occurrence)
            assert span is not None  # raw_problems checked the text and occurrence
            same_type, same_truth = label["type"] == claim["type"], label["truth"] == claim["truth"]
            common = {
                "claim_id": claim["claim_id"],
                "text": claim["text"],
                "occurrence": occurrence,
                "span": list(span),
            }
            if same_type and same_truth:
                kept[str(claim["type"])] += 1
                gold.append(
                    {
                        **common,
                        "claim_type": claim["type"],
                        "verdict": claim["truth"],
                        "evidence_lines": claim["evidence_lines"],
                        "adjudicator_evidence_lines": label["evidence_lines"],
                    }
                )
                continue
            reason = _drop_reason(same_type, same_truth)
            drops.setdefault(str(claim["type"]), Counter())[reason] += 1
            types = [str(claim["type"])] + ([] if same_type else [str(label["type"])])
            ignored.append(
                {
                    **common,
                    "claim_types": types,
                    "reason": reason,
                    "writer_type": claim["type"],
                    "writer_truth": claim["truth"],
                    "adjudicator_type": label["type"],
                    "adjudicator_truth": label["truth"],
                }
            )
        reports.append(
            {
                "report_id": report_id,
                "run_id": raw["run_id"],
                "writer": writer,
                "adjudicator": adjudicator,
                "report": raw["report"],
                "gold": gold,
                "ignored": ignored,
            }
        )
    return {
        "schema": "receipts.e0.merged/1",
        "synthetic": True,
        "note": SYNTHETIC_NOTE,
        "reports": reports,
        "kept_by_type": dict(sorted(kept.items())),
        "drops": {
            "by_type": {t: dict(sorted(c.items())) for t, c in sorted(drops.items())},
            "total": sum(sum(c.values()) for c in drops.values()),
        },
        "excluded_reports": excluded,
    }


def merge_artifact(
    root: Path,
    raw_dir: Path,
    adjudication_dir: Path,
    blindness_path: Path | None,
    *,
    command: str,
    agents: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """:func:`merge_reports` with provenance and the blindness file it used.

    ``blindness`` records that file's path, SHA-256, and ``rescanned``: with ``agents``
    (the transcripts it scanned), the file must be what a new scan of them gives
    (:func:`_check_rescan`). Raises E0Error for ``agents`` without a blindness file.
    """
    if agents is not None and blindness_path is None:
        raise E0Error("--agents needs --blindness")
    blindness: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    if blindness_path is not None:
        blindness, _, _, record = _load_blindness(root, blindness_path, agents)
    merged = merge_reports(raw_dir, adjudication_dir, blindness)
    merged["blindness"] = record
    merged["provenance"] = provenance(root, command)
    return merged


# ---------------------------------------------------------------- 8. split


def split_of(report_id: str) -> str:
    """``"heldout"`` or ``"dev"`` for a report id, by :data:`SPLIT_RULE`."""
    return "heldout" if int(seeded_rank(report_id), 16) % 2 == 1 else "dev"


def scored_ledger(
    root: Path, report_id: str, run_id: str, packet: Mapping[str, Any] | None, where: Path
) -> tuple[str, str]:
    """``(ledger SHA-256, fact sheet SHA-256)`` of the smoke ledger a report is scored on.

    The ledger at ``SMOKE_LEDGER`` must be the one the writer's packet was built from
    (``packet``, the run's entry in the writer index at ``where``): the same bytes, and a
    numbered fact sheet with the hash the writer saw. Otherwise the gold labels and the
    verifier would judge different records. Raises E0Error when it is not.
    """
    ledger_rel = SMOKE_LEDGER.format(run_id=run_id)
    ledger_path = root / ledger_rel
    if packet is None:
        raise E0Error(f"report {report_id}: run {run_id} has no writer packet in {where}")
    if not ledger_path.is_file():
        raise E0Error(f"report {report_id}: its ledger {ledger_rel} is missing")
    ledger_sha = sha256_file(ledger_path)
    if ledger_sha != packet.get("ledger_sha256"):
        raise E0Error(
            f"report {report_id}: {ledger_rel} is not the ledger its writer packet was built from"
        )
    try:
        sheet, _ = numbered_fact_sheet(Ledger.load(ledger_path))
    except ValueError as exc:
        raise E0Error(f"report {report_id}: cannot load {ledger_rel} ({exc})") from exc
    sheet_sha = sha256_bytes(sheet.encode("utf-8"))
    if sheet_sha != packet.get("fact_sheet_sha256"):
        raise E0Error(
            f"report {report_id}: the fact sheet of {ledger_rel} differs from the one its "
            "writer saw"
        )
    return ledger_sha, sheet_sha


def write_split(
    root: Path, merged_path: Path, packets_dir: Path, *, command: str
) -> dict[str, Any]:
    """Write the dev and held-out seeded reports and the held-out manifest.

    Each report file holds the report, its gold and ignored claims, and the path and
    SHA-256 of its run's ledger (``SMOKE_LEDGER``), which must be the ledger the writer's
    packet came from (:func:`scored_ledger`, against the writer index in
    ``packets_dir``). The manifest lists the SHA-256 of every held-out file's bytes.
    Raises E0Error when the manifest or any held-out file is already committed (the
    held-out half is frozen), or when a ledger is missing or not the writer's.
    """
    if tracked(root, MANIFEST) or tracked(root, f"{SEEDED}/heldout"):
        raise E0Error(f"{MANIFEST} or a held-out report is committed; the split is frozen")
    merged = load_json(merged_path)
    if not isinstance(merged, dict) or merged.get("schema") != "receipts.e0.merged/1":
        raise E0Error(f"{merged_path} is not a merged E0 artifact")
    reports = list(merged.get("reports", []))
    if not reports:
        raise E0Error(f"{merged_path} has no reports")
    index_path = packets_dir / "index.json"
    packets = {str(entry["run_id"]): entry for entry in writer_index(packets_dir)}
    documents: dict[str, tuple[str, str]] = {}
    gold_by_type: Counter[str] = Counter()
    ignored_by_type: Counter[str] = Counter()
    dev_reports = 0
    for report in reports:
        report_id, run_id = str(report["report_id"]), str(report["run_id"])
        half = split_of(report_id)
        ledger_rel = SMOKE_LEDGER.format(run_id=run_id)
        packet = packets.get(run_id)
        ledger_sha, sheet_sha = scored_ledger(root, report_id, run_id, packet, packets_dir)
        assert packet is not None  # scored_ledger refuses a run without a packet
        document = {
            "schema": "receipts.e0.seeded_report/1",
            "synthetic": True,
            "note": SYNTHETIC_NOTE,
            "split": half,
            "report_id": report_id,
            "run_id": run_id,
            "writer": report["writer"],
            "adjudicator": report["adjudicator"],
            "ledger": ledger_rel,
            "ledger_sha256": ledger_sha,
            "fact_sheet_sha256": sheet_sha,
            "writer_packet_sha256": packet.get("sha256"),
            "report": report["report"],
            "gold": report["gold"],
            "ignored": report["ignored"],
        }
        documents[report_id] = (half, dump_json(document))
        if half == "heldout":
            gold_by_type.update(str(g["claim_type"]) for g in report["gold"])
            ignored_by_type.update(str(c["claim_types"][0]) for c in report["ignored"])
        else:
            dev_reports += 1
    hashes = {
        rid: sha256_bytes(text.encode("utf-8"))
        for rid, (half, text) in documents.items()
        if half == "heldout"
    }
    if not hashes:
        raise E0Error("no report fell in the held-out half")
    for half in ("dev", "heldout"):
        directory = root / SEEDED / half
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.json"):
            stale.unlink()
    for report_id, (half, text) in documents.items():
        (root / SEEDED / half / f"{report_id}.json").write_bytes(text.encode("utf-8"))
    manifest = {
        "schema": "receipts.e0.heldout_manifest/1",
        "seed": SPLIT_SEED,
        "split_rule": SPLIT_RULE,
        "reports": dict(sorted(hashes.items())),
        "gold_by_type": dict(sorted(gold_by_type.items())),
        "ignored_by_type": dict(sorted(ignored_by_type.items())),
        "dev_reports": dev_reports,
        "drops": merged.get("drops", {}),
        "excluded_reports": merged.get("excluded_reports", []),
        "merged": {"path": display_path(root, merged_path), "sha256": sha256_file(merged_path)},
        "writer_packets": {
            "path": display_path(root, index_path),
            "sha256": sha256_file(index_path),
        },
        "provenance": provenance(root, command),
    }
    write_json(root / MANIFEST, manifest)
    return manifest


# ---------------------------------------------------------------- 9. evaluate


def check_frozen_heldout(root: Path) -> dict[str, Any]:
    """The committed held-out manifest, after checking that nothing held out changed.

    The manifest must be committed, have no uncommitted change, and be untouched by any
    commit after the one that added it; the held-out directory must hold exactly its
    reports, each with the SHA-256 it lists. Raises E0Error otherwise.
    """
    added = git(root, "log", "--format=%H", "--diff-filter=A", "--", MANIFEST).split()
    if not added or not tracked(root, MANIFEST):
        raise E0Error(f"{MANIFEST} is not committed; commit it before evaluating")
    if uncommitted(root, MANIFEST):
        raise E0Error(f"{MANIFEST} has uncommitted changes")
    if git(root, "log", "--format=%H", f"{added[-1]}..HEAD", "--", MANIFEST).split():
        raise E0Error(f"{MANIFEST} changed after the commit that added it")
    manifest = load_json(root / MANIFEST)
    if not isinstance(manifest, dict):
        raise E0Error(f"{MANIFEST} is not a JSON object")
    reports = manifest.get("reports")
    if not isinstance(reports, dict) or not reports:
        raise E0Error(f"{MANIFEST} lists no held-out reports")
    directory = root / SEEDED / "heldout"
    present = {path.stem for path in directory.glob("*.json")}
    if present != set(reports):
        raise E0Error(f"{directory} does not hold exactly the reports its manifest lists")
    for report_id, digest in reports.items():
        if sha256_file(directory / f"{report_id}.json") != digest:
            raise E0Error(f"held-out report {report_id} changed since the manifest")
    return manifest


def subject(params: Mapping[str, object]) -> str:
    """What a predicted claim is about: its first non-empty subject parameter, or ""."""
    for key in _SUBJECT_KEYS:
        value = params.get(key)
        if value is not None and str(value):
            return str(value)
    return ""


def task_requirements(root: Path, task_id: str) -> dict[str, str]:
    """The requirement texts of the benchmark task ``root/bench/tasks/<task_id>/``.

    ``TaskSpec.requirement_texts()`` of :func:`receipts.bench.spec.load_task`: the mapping
    ``receipts.study.rescore.task_requirements`` gives the banking and the runner gives
    the verifier (a contract test keeps the two equal). Raises E0Error when ``task_id``
    is not a plain id, the task does not exist, or its files break the task spec.
    """
    if not is_id(task_id):
        raise E0Error(f"task id {task_id!r} is not a plain id")
    task_dir = root / TASKS_DIR / task_id
    if not task_dir.is_dir():
        raise E0Error(f"no task {task_id!r} under {TASKS_DIR}")
    try:
        return dict(load_task(task_dir).requirement_texts())
    except (ValueError, OSError) as exc:  # TaskSpecError is a ValueError
        raise E0Error(f"task {task_id} does not load ({exc})") from exc


def requirements_sha256(requirements: Mapping[str, str]) -> str:
    """SHA-256 of a requirement mapping as canonical JSON (sorted keys, compact, UTF-8)."""
    return sha256_text(canonical_json(dict(requirements)))


def predict(report: str, ledger: Ledger, requirements: Mapping[str, str]) -> list[PredictedClaim]:
    """The instrument's claims for ``report``: the pattern extractor, then the verifier.

    The verifier runs in :data:`VERIFIER_MODE`: ``requirements`` are the requirement
    texts of the run's task (:func:`task_requirements`), so a ``bug_fixed``,
    ``feature_implemented``, or ``could_not`` claim is judged on the hidden checks of the
    requirements it maps to. An empty mapping is passed as None, as the runner and the
    banking pass a task without requirements.
    """
    from receipts.claims.extract import extract_claims  # scoring only (blindness)
    from receipts.verify import verify_run

    claims = extract_claims(report)
    verification = verify_run(
        claims, ledger, requirements=dict(requirements) or None, report=report
    )
    return [
        PredictedClaim(c.type.value, c.span, v.label.value, c.claim_id, subject(c.params))
        for c, v in zip(verification.claims, verification.verdicts, strict=True)
    ]


def _span(value: object) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(_is_int(v) for v in value):
        raise E0Error(f"bad span {value!r}")
    return (int(value[0]), int(value[1]))


def score_document(
    root: Path, document: Mapping[str, Any]
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """Scoring items for one seeded report file, and the requirements it was verified with.

    The report's ledger must match its hash. The verifier runs in :data:`VERIFIER_MODE`,
    with the requirement texts of the task that the ledger's ``run_start`` names
    (:func:`task_requirements`); the second value records them as ``task_id`` and
    ``requirements_sha256`` (:func:`requirements_sha256`). Raises E0Error when the
    ledger is missing or changed, or names no task whose requirements load: the report
    is never verified without them.
    """
    report_id = str(document["report_id"])
    ledger_path = root / str(document["ledger"])
    if not ledger_path.is_file() or sha256_file(ledger_path) != document.get("ledger_sha256"):
        raise E0Error(f"report {report_id}: ledger {document['ledger']} is missing or changed")
    ledger = Ledger.load(ledger_path)
    start = ledger.run_start()
    task_id = start.data.get("task_id") if start is not None else None
    if not isinstance(task_id, str) or not is_id(task_id):
        raise E0Error(
            f"report {report_id}: its ledger's run_start names no plain task id ({task_id!r})"
        )
    try:
        requirements = task_requirements(root, task_id)
    except E0Error as exc:
        raise E0Error(f"report {report_id}: {exc}") from exc
    gold = [
        GoldClaim(
            str(g["claim_type"]),
            _span(g["span"]),
            str(g["verdict"]),
            str(g["claim_id"]),
            str(g["text"]),
        )
        for g in document["gold"]
    ]
    ignored = [
        IgnoredClaim(
            tuple(map(str, c["claim_types"])), _span(c["span"]), str(c["claim_id"]), str(c["text"])
        )
        for c in document["ignored"]
    ]
    predicted = predict(str(document["report"]), ledger, requirements)
    record = {"task_id": task_id, "requirements_sha256": requirements_sha256(requirements)}
    return report_items(report_id, gold, predicted, ignored), record


def type_entry(result: TypeScore) -> dict[str, Any]:
    """One ``per_type`` entry of ``seeded_eval.json``.

    It meets the thresholds only with predictions and gold claims and P >= 0.95 and
    R >= 0.90 (both bounds inclusive, as gate G5 reads them); undefined rates are None.
    """
    has_pred, has_gold = result.predicted > 0, result.gold > 0
    meets = (
        has_pred and has_gold and result.precision >= PRECISION_MIN and result.recall >= RECALL_MIN
    )
    return {
        "correct": result.correct,
        "predicted": result.predicted,
        "gold": result.gold,
        "ignored": result.ignored,
        "precision": result.precision if has_pred else None,
        "precision_ci": list(result.precision_ci()) if has_pred else None,
        "recall": result.recall if has_gold else None,
        "recall_ci": list(result.recall_ci()) if has_gold else None,
        "meets_thresholds": meets,
    }


def blind_label_counts(counts: Mapping[str, Any]) -> dict[str, int]:
    """The counts of a blind-label counts artifact, once they recompute from its labels.

    ``labels`` must be a list of ``{"claims": [{"type": ...}]}`` entries, and the non-zero
    ``counts`` must equal the number of labeled claims of each type (a zero entry is no
    count, as gate G5 reads it). Returns the recount; raises E0Error otherwise.
    """
    labels = counts.get("labels")
    if not (
        isinstance(labels, list)
        and all(
            isinstance(entry, dict)
            and isinstance(entry.get("claims"), list)
            and all(isinstance(c, dict) and isinstance(c.get("type"), str) for c in entry["claims"])
            for entry in labels
        )
    ):
        raise E0Error(f"{COUNTS} has no blind labels")
    recount = Counter(str(claim["type"]) for entry in labels for claim in entry["claims"])
    values = counts.get("counts")
    if not isinstance(values, dict) or not all(_is_int(v) for v in values.values()):
        raise E0Error(f"{COUNTS} has no counts")
    if {str(name): int(value) for name, value in values.items() if value} != dict(recount):
        raise E0Error(f"{COUNTS} counts do not recompute from its blind labels")
    return dict(recount)


def heldout_counts(counts: object, instrument: Mapping[str, Any]) -> dict[str, int]:
    """The claim-type counts the held-out evaluation ranks its top five from, once checked.

    Blind-label counts (``COUNTS_METHOD``, D34) must recompute from their labels
    (:func:`blind_label_counts`); no extractor made them, so they are not bound to the
    instrument. Extractor counts (``EXTRACTOR_METHOD``, as written before D34) must be the
    counts of the real smoke runs (``SMOKE_RUNS``), made on a committed instrument whose
    trees (INSTRUMENT_PATHS) equal the evaluated ones, so their top five come from the
    extractor version under test. Raises E0Error otherwise.
    """
    if not isinstance(counts, dict):
        raise E0Error(f"{COUNTS} is not a JSON object")
    method = counts.get("method")
    if method == COUNTS_METHOD:
        return blind_label_counts(counts)
    if method != EXTRACTOR_METHOD:
        raise E0Error(
            f"{COUNTS} was counted by method {method!r}, not {COUNTS_METHOD!r} or "
            f"{EXTRACTOR_METHOD!r}"
        )
    if counts.get("runs_dir") != SMOKE_RUNS:
        raise E0Error(
            f"{COUNTS} counts the runs under {counts.get('runs_dir')!r}, not {SMOKE_RUNS}"
        )
    made = counts.get("instrument")
    if not isinstance(made, dict) or made.get("dirty") is not False:
        raise E0Error(f"{COUNTS} was counted while the instrument had uncommitted changes")
    trees = made.get("trees")
    current = instrument["trees"]
    changed = [
        rel
        for rel in INSTRUMENT_PATHS
        if not isinstance(trees, dict) or rel not in trees or trees[rel] != current.get(rel)
    ]
    if changed:
        raise E0Error(
            f"{COUNTS} was counted with a different instrument ({', '.join(changed)} changed "
            "since); run the counts step again"
        )
    values = counts.get("counts")
    if not isinstance(values, dict) or not all(_is_int(v) for v in values.values()):
        raise E0Error(f"{COUNTS} has no counts")
    return {str(name): int(value) for name, value in values.items()}


def log_attempt(root: Path, result: Mapping[str, Any], command: str) -> int:
    """Append one held-out evaluation to ``ATTEMPTS`` and return its attempt number.

    The line records when it ran, the command, the instrument's commit and trees, and the
    per-type counts and passes of the top five, so every scoring of the held-out half
    stays visible once committed.
    """
    path = root / ATTEMPTS
    earlier = path.read_text(encoding="utf-8").split("\n") if path.is_file() else []
    attempt = sum(1 for line in earlier if line.strip()) + 1
    per_type = result["per_type"]
    entry = {
        "attempt": attempt,
        "created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "command": command,
        "commit": result["instrument"]["commit"],
        "trees": result["instrument"]["trees"],
        "passes": result["passes"],
        "all_top5_pass": result["all_top5_pass"],
        "per_type": {
            name: {key: per_type[name][key] for key in ("correct", "predicted", "gold")}
            for name in result["top5"]
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return attempt


def score_split(root: Path, split: str, instrument: Mapping[str, Any]) -> dict[str, Any]:
    """The scoring of the seeded ``split``: what :func:`evaluate` records, and what
    :func:`recheck` derives again, on this one path.

    For ``heldout`` it scores the reports of the frozen held-out manifest
    (:func:`check_frozen_heldout`) and ranks the top five from counts that pass
    :func:`heldout_counts` (against ``instrument``, the caller's
    :func:`instrument_state`); for ``dev`` every dev report and whatever counts exist.
    Every report is verified in :data:`VERIFIER_MODE` (:func:`score_document`), and
    ``verifier_mode`` and ``report_requirements`` (each scored report's ``task_id`` and
    ``requirements_sha256``) record it. A top-five type passes only with predictions and
    gold claims and P >= 0.95 and R >= 0.90, and all pass only when five types were
    counted. It refuses nothing about the instrument, logs no attempt, and writes no
    file; the result has every field of the evaluation but ``instrument``, ``attempt``,
    and ``provenance``.
    """
    if split not in ("heldout", "dev"):
        raise E0Error(f"unknown split {split!r}")
    heldout = split == "heldout"
    manifest_sha = None
    counts_path = root / COUNTS
    if heldout:
        manifest = check_frozen_heldout(root)
        files = [root / SEEDED / "heldout" / f"{rid}.json" for rid in sorted(manifest["reports"])]
        manifest_sha = sha256_file(root / MANIFEST)
        if not counts_path.is_file():
            raise E0Error(f"{COUNTS} is missing; run the counts step first")
        counts_data = load_json(counts_path)
        counted = heldout_counts(counts_data, instrument)
    else:
        files = sorted((root / SEEDED / "dev").glob("*.json"))
        if not files:
            raise E0Error(f"no dev reports in {root / SEEDED / 'dev'}")
        counts_data = load_json(counts_path) if counts_path.is_file() else {}
        counted = dict(counts_data.get("counts", {})) if isinstance(counts_data, dict) else {}
    method = counts_data.get("method") if isinstance(counts_data, dict) else None
    top5 = top_types(counted)
    items: list[dict[str, object]] = []
    verified: dict[str, dict[str, str]] = {}
    for path in files:
        document = load_json(path)
        report_id = str(document["report_id"])
        if report_id in verified:
            raise E0Error(f"report {report_id} appears in more than one seeded report file")
        scored, verified[report_id] = score_document(root, document)
        items.extend(scored)
    scores = score(items)
    for name in top5:
        scores.setdefault(name, TypeScore(name, 0, 0, 0))
    per_type = {name: type_entry(result) for name, result in sorted(scores.items())}
    passes = {name: bool(per_type[name]["meets_thresholds"]) for name in top5}
    return {
        "schema": "receipts.e0.seeded_eval/1",
        "split": split,
        "synthetic_reports": True,
        "note": SYNTHETIC_NOTE,
        "heldout_manifest": MANIFEST if heldout else None,
        "heldout_manifest_sha256": manifest_sha,
        "claim_type_counts": COUNTS if counts_path.is_file() else None,
        "claim_type_counts_sha256": sha256_file(counts_path) if counts_path.is_file() else None,
        "claim_type_counts_method": method,
        "verifier_mode": VERIFIER_MODE,
        "report_requirements": dict(sorted(verified.items())),
        "reports": len(files),
        "items": items,
        "per_type": per_type,
        "top5": top5,
        "thresholds": {"precision": PRECISION_MIN, "recall": RECALL_MIN},
        "passes": passes,
        "all_top5_pass": len(top5) == TOP_N and all(passes.values()),
        "matching": MATCHING_RULE,
        "attempts_log": ATTEMPTS if heldout else None,
    }


def evaluate(
    root: Path, split: str = "heldout", *, command: str, allow_dirty: bool = False
) -> dict[str, Any]:
    """Score the instrument on the seeded ``split`` (``heldout`` for G5, or ``dev``).

    For ``heldout``: ``allow_dirty`` is refused; SCORING_PATHS must have no uncommitted
    change; :func:`check_frozen_heldout` must pass; ``claim_type_counts.json`` must pass
    :func:`heldout_counts`; and ``ATTEMPTS`` must have no uncommitted change. The run is
    then logged there (:func:`log_attempt`) and numbered in ``attempt``. A top-five type
    passes only with predictions and gold claims and P >= 0.95 and R >= 0.90, and all
    pass only when five types were counted. ``dev`` checks none of this (it is the
    development loop, so a dirty instrument is recorded, not refused), is not logged,
    and is never read by the gate.

    Both splits verify every report in :data:`VERIFIER_MODE` (:func:`score_document`)
    and record it: ``verifier_mode``, and ``report_requirements`` with each scored
    report's ``task_id`` and ``requirements_sha256``. The scoring is :func:`score_split`,
    which :func:`recheck` runs again; this adds the ``instrument`` record, the
    ``attempt``, and the ``provenance``.
    """
    if split not in ("heldout", "dev"):
        raise E0Error(f"unknown split {split!r}")
    heldout = split == "heldout"
    if heldout and allow_dirty:
        raise E0Error("--allow-dirty is not allowed for the held-out split")
    instrument = instrument_state(root, SCORING_PATHS, allow_dirty=allow_dirty)
    if heldout:
        refuse_dirty(instrument)
        if uncommitted(root, ATTEMPTS):
            raise E0Error(
                f"{ATTEMPTS} has uncommitted changes: commit the earlier held-out attempt "
                "before scoring again"
            )
    result = score_split(root, split, instrument)
    result["instrument"] = instrument
    result["attempt"] = None
    result["provenance"] = provenance(root, command)
    if heldout:
        result["attempt"] = log_attempt(root, result, command)
    return result


_HEX40 = re.compile(r"[0-9a-f]{40}")


def is_commit(root: Path, sha: object) -> bool:
    """True if ``sha`` is the full hex name of a commit of ``root``."""
    if not isinstance(sha, str) or _HEX40.fullmatch(sha) is None:
        return False
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def loaded_sources(root: Path) -> list[str]:
    """The files under ``root/src`` of the modules this process has loaded, relative to
    ``root`` and sorted: after a scoring, the code that scoring ran. :data:`PACKAGE_INIT`
    is left out, as gate G5 leaves it out of the instrument it binds."""
    base, top = (root / "src").resolve(), root.resolve()
    found: set[str] = set()
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if isinstance(name, str):
            path = Path(name).resolve()
            if path.is_relative_to(base):
                found.add(path.relative_to(top).as_posix())
    found.discard(PACKAGE_INIT)
    return sorted(found)


def require_evaluated_code(root: Path, recorded: Mapping[str, Any]) -> None:
    """Refuse unless this process scored with the code of the evaluation's instrument
    commit (``instrument.commit`` in ``recorded``, a commit of ``root``): every file
    :func:`loaded_sources` lists must have no uncommitted change and be the same git blob
    at HEAD as at that commit. So :func:`recheck` never reports a scoring of the held-out
    half made with other code, which would be a held-out attempt that no log records;
    scoring a revised instrument is a new attempt, which :func:`evaluate` logs. Gate G5
    already holds the instrument files unchanged since that commit, so in its clone this
    refuses nothing G5 would pass. Raises E0Error naming up to five differing files."""
    instrument = recorded.get("instrument")
    sha = instrument.get("commit") if isinstance(instrument, dict) else None
    if not is_commit(root, sha):
        raise E0Error(
            f"{EVAL} records no evaluated commit of this repository (instrument.commit "
            f"{sha!r}), so recheck cannot tell which code to score with"
        )
    loaded = loaded_sources(root)
    if not loaded:
        return
    changed = set(uncommitted(root, *loaded))
    changed |= {rel for rel in loaded if tree_id(root, rel, str(sha)) != tree_id(root, rel)}
    if changed:
        listed = ", ".join(sorted(changed)[:5]) + (", ..." if len(changed) > 5 else "")
        raise E0Error(
            f"the code recheck scored with is not the code of the evaluated commit "
            f"{str(sha)[:12]} ({listed}): recheck scores the held-out half only with the "
            "instrument the evaluation scored"
        )


_ABSENT = object()


def _same_json(first: object, second: object) -> bool:
    """True when two JSON values are the same: as canonical JSON, so a ``true`` is not a
    ``1`` and a ``1.0`` is not a ``1``, though Python's ``==`` takes them as equal."""
    if first is _ABSENT or second is _ABSENT:
        return first is second
    return canonical_json(first) == canonical_json(second)


def _shown(value: object) -> str:
    """A short form of a JSON value for a message (at most 60 characters)."""
    if value is _ABSENT:
        return "no value"
    text = canonical_json(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _differing_keys(first: Mapping[str, Any], second: Mapping[str, Any]) -> list[str]:
    """The keys whose values differ between two JSON objects (a key one lacks included)."""
    return sorted(
        str(key)
        for key in set(first) | set(second)
        if not _same_json(first.get(key, _ABSENT), second.get(key, _ABSENT))
    )


def _first_item_difference(old: Sequence[object], fresh: Sequence[Mapping[str, Any]]) -> str:
    """The first scoring item that differs between the file's list (``old``) and the new
    scoring (``fresh``): its index, report, and claim type, and the keys that differ."""
    for index in range(max(len(old), len(fresh))):
        was = old[index] if index < len(old) else _ABSENT
        new = fresh[index] if index < len(fresh) else _ABSENT
        if _same_json(was, new):
            continue
        shown = new if isinstance(new, dict) else was if isinstance(was, dict) else {}
        label = f"items[{index}] (report {shown.get('report_id')}, {shown.get('claim_type')})"
        if was is _ABSENT:
            return f"{label} is only in the new scoring"
        if new is _ABSENT:
            return f"{label} is only in the file"
        if not isinstance(was, dict) or not isinstance(new, dict):
            return f"{label} is not an object in the file"
        keys = _differing_keys(was, new)
        return f"{label}: " + "; ".join(
            f"{key} {_shown(was.get(key, _ABSENT))} in the file, "
            f"{_shown(new.get(key, _ABSENT))} scored again"
            for key in keys[:3]
        )
    return ""


def recheck_differences(recorded: Mapping[str, Any], fresh: Mapping[str, Any]) -> list[str]:
    """How the evaluation ``recorded`` differs from the new scoring ``fresh`` in
    :data:`RECHECKED_FIELDS`, compared as JSON: one entry per differing field, in that
    order, naming the first three keys that differ in an object (``per_type
    (file_modified)``), ``(missing)`` for a field the file lacks, or ``(not a list in the
    file)`` for items that are not a list, and then, when two lists of items differ, the
    first differing item. Empty when they agree."""
    out: list[str] = []
    item = ""
    for name in RECHECKED_FIELDS:
        if name not in recorded:
            out.append(f"{name} (missing)")
            continue
        was, new = recorded[name], fresh[name]
        if _same_json(was, new):
            continue
        if isinstance(was, dict) and isinstance(new, dict):
            keys = _differing_keys(was, new)
            listed = ", ".join(keys[:3]) + (", ..." if len(keys) > 3 else "")
            out.append(f"{name} ({listed})")
        elif name == "items" and not isinstance(was, list):
            out.append(f"{name} (not a list in the file)")
        else:
            out.append(name)
            if name == "items":
                item = _first_item_difference(was, new)
    return out + ([f"first differing item: {item}"] if item else [])


def recheck(root: Path) -> dict[str, Any]:
    """Score the held-out half again and require ``EVAL`` to hold that result (gate G5,
    review B6, DECISIONS D66). Returns the evaluation as the file holds it.

    No model is called and nothing changes: it logs no attempt and writes no file. It
    reads ``EVAL``, requires the held-out split, and scores every report of the frozen
    held-out manifest again through :func:`score_split`, the path :func:`evaluate`
    takes, with the committed instrument at HEAD (SCORING_PATHS must have no uncommitted
    change, so the code re-run is the code a commit holds), and reports nothing unless the
    code it scored with is the code of the evaluated commit (:func:`require_evaluated_code`).
    Every field of :data:`RECHECKED_FIELDS` must equal the new result as JSON
    (:func:`recheck_differences`), so a prediction typed into the file, a typed per-type
    value or pass, or a requirement text edited after the scoring (its digest in
    ``report_requirements``, D54) shows.
    Raises :class:`RecheckMismatchError` naming the differing fields and the first differing
    item, and E0Error when it cannot score again: ``EVAL`` missing, not a JSON object, or
    not the held-out split; a dirty instrument; a step :func:`score_split` refuses (a
    held-out half or ledger changed since it was frozen, unchecked counts, or a task whose
    requirements do not load); or scoring code other than the evaluated commit's.
    """
    recorded, error = read_json(root / EVAL)
    if error is not None:
        raise E0Error(f"{EVAL}: {error}")
    if not isinstance(recorded, dict):
        raise E0Error(f"{EVAL} is not a JSON object")
    if recorded.get("split") != "heldout":
        raise E0Error(
            f"{EVAL} is not the held-out split (split {recorded.get('split')!r}); recheck "
            "scores the held-out half"
        )
    instrument = instrument_state(root, SCORING_PATHS)
    refuse_dirty(instrument)
    fresh = json.loads(dump_json(score_split(root, "heldout", instrument)))
    require_evaluated_code(root, recorded)
    differences = recheck_differences(recorded, fresh)
    if differences:
        fields = [d for d in differences if not d.startswith("first differing item: ")]
        message = f"{EVAL} differs from a new scoring of the held-out reports in " + ", ".join(
            fields
        )
        raise RecheckMismatchError("; ".join([message, *differences[len(fields) :]]))
    return recorded


# ---------------------------------------------------------------- 10. completeness


def task_test_command(bench_dir: Path, task_id: str) -> str:
    """The visible test command of a benchmark task (``test_cmd`` in its task.toml)."""
    path = bench_dir / task_id / "task.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise E0Error(f"cannot read the test command of task {task_id} ({exc})") from exc
    value = data.get("test_cmd")
    if not isinstance(value, str) or not value:
        raise E0Error(f"{path} has no test_cmd")
    return value


def run_completeness(run: BankedRun, bench_dir: Path) -> dict[str, Any]:
    """One row of ``ledger_completeness.json`` for a minimal-agent run.

    Transcript commands start after the task request (found by the run's
    ``provenance.prompt_sha256``); ``unparsed_actions`` counts assistant messages after
    it that are not tool calls, so a protocol mismatch cannot pass silently.
    """
    from receipts.drivers.minimal_agent.protocol import ProtocolError, parse_action
    from receipts.evaluation.completeness import check_run, never_run, task_start

    start_event = run.ledger.run_start()
    agent = "" if start_event is None else str(start_event.data.get("agent", ""))
    if agent != "minimal-agent":
        raise E0Error(
            f"run {run.run_id}: completeness reads minimal-agent transcripts, not {agent!r}"
        )
    transcript = load_json(run.path / "transcript.json")
    messages = transcript.get("messages") if isinstance(transcript, dict) else None
    if not isinstance(messages, list):
        raise E0Error(f"run {run.run_id}: transcript.json has no messages")
    prompt_sha = run.record.get("provenance", {}).get("prompt_sha256")
    try:
        start = task_start(messages, str(prompt_sha))
    except ValueError as exc:
        raise E0Error(f"run {run.run_id}: {exc}") from exc
    result = check_run(
        run.run_id, messages, run.ledger, task_test_command(bench_dir, run.task_id), start=start
    )
    unparsed = 0
    for index in range(start, len(messages)):
        message = messages[index]
        if message.get("role") != "assistant":
            continue
        reply = messages[index + 1] if index + 1 < len(messages) else {}
        if never_run(str(reply.get("content", ""))):
            unparsed += 1
            continue
        try:
            parse_action(str(message.get("content", "")))
        except ProtocolError:
            unparsed += 1
    return {**result.to_dict(), "unparsed_actions": unparsed}


def completeness_artifact(
    root: Path, runs_dirs: Sequence[Path], bench_dir: Path, *, command: str
) -> dict[str, Any]:
    """``artifacts/e0/ledger_completeness.json`` over the real runs under ``runs_dirs``."""
    rows: list[dict[str, Any]] = []
    for runs_dir in runs_dirs:
        rows.extend(run_completeness(run, bench_dir) for run in real_runs(load_runs(runs_dir)))
    if not rows:
        raise E0Error("no real runs to check")
    ids = [row["run_id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise E0Error("a run id appears in more than one runs directory")
    return {
        "schema": "receipts.e0.ledger_completeness/1",
        "runs_dirs": [display_path(root, d) for d in runs_dirs],
        "runs": rows,
        "total_missing": sum(len(row["missing"]) for row in rows),
        "provenance": provenance(root, command),
    }
