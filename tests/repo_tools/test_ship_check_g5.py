"""Gate G5 of tools/ship_check.py on synthetic E0 artifacts (H12, H14, H19 to H21, H23,
and review-3 of the harness review round).

Every artifact here is SYNTHETIC, made up only to exercise ``ship_check.g5`` in throwaway
git repositories: smoke-run rows, blind labels, seeded reports and their gold claims,
scoring items, and ledger completeness rows. Smoke rows are marked ``synthetic: false``
only so the gate treats them as real runs. The "instrument" is a small stand-in package
of one-line modules. Nothing here is a model result or a real-world result.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import ship_check
from receipts.ledger.events import GENESIS, Event

Commit = Callable[[Path, str], str]
GateError = ship_check.GateError

AGENT = "minimal-agent/qwen2.5-coder-7b-instruct-q4km"
TYPES = ("tests_pass", "file_modified", "ran_command", "test_count", "task_complete")
PROV = {
    "git_sha": "0" * 40,
    "command": "SYNTHETIC test fixture",
    "created": "2026-11-04T00:00:00+00:00",
}
SMOKE_IDS = tuple(f"smoke-t{i}" for i in range(5))
# SYNTHETIC blind-label counts: the five TYPES are the five most common.
COUNTS = {
    "tests_pass": 9,
    "file_modified": 8,
    "ran_command": 7,
    "test_count": 6,
    "task_complete": 5,
    "bug_fixed": 1,
}
MANIFEST = "artifacts/e0/heldout_manifest.json"
EVAL = "artifacts/e0/seeded_eval.json"
E0_MODULE = "src/receipts/evaluation/e0.py"
SEEDED = "src/receipts/evaluation/seeded.py"
CHECKERS = "src/receipts/verify/checkers.py"
# A SYNTHETIC stand-in package with the import structure of the real one: the E0 module
# imports the scorer, fact sheets, and ledger reader at module level, the extractor and
# verifier inside predict, and its completeness step inside that step. E2 and E3 code,
# the ledger writer, and the sandbox sit beside it and are never loaded by scoring.
E0_STANDIN = '''"""SYNTHETIC stand-in for the E0 module."""

from receipts.evaluation import GOLD
from receipts.evaluation.facts import FACTS
from receipts.evaluation.seeded import SCORE
from receipts.ledger.events import EVENTS


def predict() -> int:
    from receipts.claims import RULES
    from receipts.verify import CHECKS

    return GOLD + FACTS + SCORE + EVENTS + RULES + CHECKS


def run_completeness() -> int:
    from receipts.evaluation.completeness import CHECK

    return CHECK
'''
INSTRUMENT = {
    "src/receipts/__init__.py": '__version__ = "0"\n',
    "src/receipts/claims/__init__.py": "from receipts.claims.patterns import RULES\n",
    "src/receipts/claims/patterns.py": "# SYNTHETIC stand-in for the extractor\nRULES = 1\n",
    "src/receipts/verify/__init__.py": "from receipts.verify.checkers import CHECKS\n",
    CHECKERS: "# SYNTHETIC stand-in for the verifier\n"
    "from receipts.ledger.events import EVENTS\n\nCHECKS = EVENTS\n",
    "src/receipts/ledger/__init__.py": "from receipts.ledger.events import EVENTS\n",
    "src/receipts/ledger/events.py": "# SYNTHETIC stand-in for the ledger reader\nEVENTS = 1\n",
    "src/receipts/ledger/recorder.py": "# SYNTHETIC stand-in for the ledger writer\n"
    "from receipts.sandbox.api import RUN\n",
    "src/receipts/sandbox/__init__.py": "",
    "src/receipts/sandbox/api.py": "# SYNTHETIC stand-in for the sandbox\nRUN = 1\n",
    "src/receipts/evaluation/__init__.py": "GOLD = 1\n",
    E0_MODULE: E0_STANDIN,
    SEEDED: "# SYNTHETIC stand-in for the scorer\nSCORE = 1\n",
    "src/receipts/evaluation/facts.py": "from receipts.ledger.events import EVENTS\n\nFACTS = 1\n",
    "src/receipts/evaluation/completeness.py": "# SYNTHETIC completeness step\nCHECK = 1\n",
    "src/receipts/evaluation/judges.py": "# SYNTHETIC stand-in for the E3 judges\nJUDGES = 1\n",
    "src/receipts/evaluation/e3.py": "from receipts.evaluation.judges import JUDGES\n",
    "src/receipts/evaluation/mechanism.py": "# SYNTHETIC stand-in for E2\nMECHANISM = 1\n",
}
# The paths tools/e0.py checks for uncommitted changes before a held-out evaluation.
CHECKED_PATHS = (
    "src/receipts/claims",
    "src/receipts/verify",
    "src/receipts/ledger",
    "src/receipts/evaluation",
)


def put(root: Path, rel: str, data: Any) -> None:
    """Write text, or JSON in the artifact format, creating parent directories."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def smoke_rows(extra: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """SYNTHETIC smoke-run rows, one per task, marked as real runs."""
    rows: list[dict[str, Any]] = [
        {"run_id": rid, "task_id": f"t{i}", "agent": AGENT, "synthetic": False}
        for i, rid in enumerate(SMOKE_IDS)
    ]
    return rows + [dict(r) for r in extra]


def labels(counts: Mapping[str, int], run_ids: Sequence[str] = SMOKE_IDS) -> list[dict[str, Any]]:
    """SYNTHETIC blind labels spread over ``run_ids``, adding up to ``counts``."""
    claims = [{"type": t, "text": f"claim {n}"} for t, k in counts.items() for n in range(k)]
    return [{"run_id": rid, "claims": claims[i :: len(run_ids)]} for i, rid in enumerate(run_ids)]


def counts_artifact(counts: Mapping[str, int] = COUNTS, **over: Any) -> dict[str, Any]:
    """A SYNTHETIC claim_type_counts.json counted from blind labels."""
    data: dict[str, Any] = {
        "method": "blind-labels",
        "labels": labels(counts),
        "counts": dict(counts),
        "source_runs": list(SMOKE_IDS),
        "provenance": PROV,
    }
    data.update(over)
    return data


def gold(
    per_type: int = 20, verdict: str = "supported", types: Sequence[str] = TYPES
) -> list[dict[str, Any]]:
    """SYNTHETIC gold claims, ``per_type`` of each type, with distinct spans."""
    out: list[dict[str, Any]] = []
    for ctype in types:
        for n in range(per_type):
            start = len(out) * 10
            out.append(
                {
                    "claim_id": f"g{len(out)}",
                    "claim_type": ctype,
                    "span": [start, start + 8],
                    "verdict": verdict,
                    "text": f"synthetic claim {n}",
                }
            )
    return out


def doc(report_id: str, claims: Sequence[Any], ignored: Sequence[Any] = ()) -> dict[str, Any]:
    """A SYNTHETIC held-out seeded report file."""
    return {
        "schema": "receipts.e0.seeded_report/1",
        "synthetic": True,
        "report_id": report_id,
        "report": "SYNTHETIC report text",
        "gold": list(claims),
        "ignored": list(ignored),
    }


DOCS = {"r1": doc("r1", gold()), "r2": doc("r2", gold())}


def write_reports(root: Path, docs: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Write the held-out files and return their SHA-256 by report id."""
    hashes = {}
    for rid, data in docs.items():
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
        put(root, f"artifacts/e0/seeded/heldout/{rid}.json", text)
        hashes[rid] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hashes


def write_heldout(root: Path, docs: Mapping[str, Mapping[str, Any]], rel: str = MANIFEST) -> None:
    """Write the held-out files and their manifest."""
    put(root, rel, {"reports": write_reports(root, docs), "provenance": PROV})


def perfect_items(docs: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """SYNTHETIC scoring items: every gold claim found with its gold verdict."""
    return [
        {
            "report_id": rid,
            "claim_type": g["claim_type"],
            "gold_verdict": g["verdict"],
            "pred_verdict": g["verdict"],
        }
        for rid, data in docs.items()
        for g in data["gold"]
    ]


def seeded_eval(
    items: Sequence[Mapping[str, Any]],
    instrument: str,
    *,
    dirty: bool = False,
    paths: Sequence[str] = CHECKED_PATHS,
    **over: Any,
) -> dict[str, Any]:
    """A SYNTHETIC held-out evaluation of the stand-in instrument at commit ``instrument``;
    ``paths`` are the paths it checked for uncommitted changes."""
    data: dict[str, Any] = {
        "split": "heldout",
        "heldout_manifest": MANIFEST,
        "items": list(items),
        "instrument": {
            "commit": instrument,
            "paths": list(paths),
            "dirty": dirty,
            "uncommitted": [],
        },
        "provenance": PROV,
    }
    data.update(over)
    return data


COMMANDS = ("ls", "pytest -q")
# Every blind label below quotes "claim <n>" for some n < 30, so this report holds them all.
REPORT = "SYNTHETIC smoke report. " + " ".join(f"claim {n}." for n in range(30))


def completeness(rows: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """A SYNTHETIC ledger completeness artifact (no gaps by default)."""
    if rows is None:
        rows = [
            {
                "run_id": rid,
                "transcript_commands": list(COMMANDS),
                "ledger_commands": list(COMMANDS),
            }
            for rid in SMOKE_IDS
        ]
    return {"runs": list(rows), "provenance": PROV}


def write_ledger(path: Path, events: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
    """A hash-chained ledger written with receipts.ledger's own event hashing."""
    prev, lines = GENESIS, []
    for seq, (kind, data) in enumerate(events):
        ts = 1_700_000_000.0 + seq
        event = Event(
            seq, ts, kind, dict(data), prev, Event.compute_hash(seq, ts, kind, data, prev)
        )
        lines.append(event.to_json())
        prev = event.hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def bank_smoke(root: Path, run_id: str, task_id: str, commands: Sequence[str]) -> None:
    """Bank one SYNTHETIC smoke run: run.json, its ledger, and its transcript."""
    base_dir = root / "artifacts" / "studies" / "smoke" / "runs" / run_id
    model = AGENT.split("/", 1)[1]
    record = {"run_id": run_id, "task_id": task_id, "model": model, "report": REPORT}
    put(root, f"artifacts/studies/smoke/runs/{run_id}/run.json", record)
    start = {"run_id": run_id, "task_id": task_id, "agent": "minimal-agent", "model": model}
    events: list[tuple[str, Mapping[str, Any]]] = [("run_start", {**start, "source": "harness"})]
    events += [("command", {"cmd": cmd, "source": "agent", "exit_code": 0}) for cmd in commands]
    write_ledger(base_dir / "ledger.jsonl", events)
    messages = [
        {"role": "user", "content": "SYNTHETIC task"},
        {"role": "assistant", "content": "{}"},
    ]
    put(root, f"artifacts/studies/smoke/runs/{run_id}/transcript.json", {"messages": messages})


def base(
    root: Path,
    commit: Commit,
    *,
    counts: Mapping[str, Any] | None = None,
    extra_smoke: Sequence[Mapping[str, Any]] = (),
    commands: Mapping[str, Sequence[str]] | None = None,
    sources: Mapping[str, str] = INSTRUMENT,
) -> str:
    """Commit SYNTHETIC smoke rows with their banked runs, blind-label counts, and the
    instrument stand-ins (``sources``). ``commands`` sets a run's agent commands
    (default COMMANDS)."""
    for i, rid in enumerate(SMOKE_IDS):
        bank_smoke(root, rid, f"t{i}", (commands or {}).get(rid, COMMANDS))
    put(
        root,
        "artifacts/bench/smoke_runs.json",
        {"runs": smoke_rows(extra_smoke), "provenance": PROV},
    )
    put(
        root, "artifacts/e0/claim_type_counts.json", counts_artifact() if counts is None else counts
    )
    for rel, text in sources.items():
        put(root, rel, text)
    put(root, "README.md", "SYNTHETIC G5 test project\n")
    return commit(root, "synthetic base")


def context(root: Path, sha: str) -> ship_check.Context:
    """A Context that treats ``root`` as the fresh clone at ``sha``."""
    logs = root.parent / "logs"
    logs.mkdir(exist_ok=True)
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha=sha)


def project(
    root: Path,
    commit: Commit,
    *,
    docs: Mapping[str, Mapping[str, Any]] = DOCS,
    items: Sequence[Mapping[str, Any]] | None = None,
    completeness_rows: Sequence[Mapping[str, Any]] | None = None,
    counts: Mapping[str, Any] | None = None,
    extra_smoke: Sequence[Mapping[str, Any]] = (),
    instrument: str | None = None,
    dirty: bool = False,
    commands: Mapping[str, Sequence[str]] | None = None,
    sources: Mapping[str, str] = INSTRUMENT,
    paths: Sequence[str] = CHECKED_PATHS,
) -> tuple[ship_check.Context, str]:
    """A SYNTHETIC E0 history: base, then the frozen held-out half, then the evaluation.

    Returns the Context and the commit the stand-in instrument was evaluated at.
    """
    evaluated = base(
        root, commit, counts=counts, extra_smoke=extra_smoke, commands=commands, sources=sources
    )
    write_heldout(root, docs)
    commit(root, "freeze the held-out half")
    chosen = perfect_items(docs) if items is None else list(items)
    at = evaluated if instrument is None else instrument
    put(root, EVAL, seeded_eval(chosen, at, dirty=dirty, paths=paths))
    put(root, "artifacts/e0/ledger_completeness.json", completeness(completeness_rows))
    return context(root, commit(root, "evaluate the held-out half")), evaluated


def test_valid_e0_artifacts_pass(git_repo: Path, commit: Commit) -> None:
    ctx, _ = project(git_repo, commit)
    evidence = ship_check.g5(ctx)
    assert "tests_pass P=1.000" in evidence
    assert "ledger completeness 100% on 5 runs" in evidence


# ---------------------------------------------------------------- H12 (old code: PASS)


def test_heldout_report_rewritten_after_scoring_fails(git_repo: Path, commit: Commit) -> None:
    _, evaluated = project(git_repo, commit)
    # After scoring: drop r2's claims of one type, re-hash the manifest, and rescore.
    docs = {"r1": DOCS["r1"], "r2": doc("r2", gold(types=TYPES[:4]))}
    write_heldout(git_repo, docs)
    put(git_repo, EVAL, seeded_eval(perfect_items(docs), evaluated))
    sha = commit(git_repo, "rewrite a held-out report and rescore")
    with pytest.raises(GateError, match="held-out manifest changed after its freeze commit"):
        ship_check.g5(context(git_repo, sha))


def test_placeholder_manifest_filled_in_later_fails(git_repo: Path, commit: Commit) -> None:
    evaluated = base(git_repo, commit)
    put(git_repo, MANIFEST, {"reports": {}, "provenance": PROV})
    commit(git_repo, "placeholder manifest")
    put(git_repo, EVAL, seeded_eval([], evaluated))
    put(git_repo, "artifacts/e0/ledger_completeness.json", completeness())
    commit(git_repo, "placeholder evaluation")
    write_heldout(git_repo, DOCS)
    put(git_repo, EVAL, seeded_eval(perfect_items(DOCS), evaluated))
    sha = commit(git_repo, "choose the held-out reports and score them together")
    with pytest.raises(GateError, match="held-out manifest"):
        ship_check.g5(context(git_repo, sha))


def test_evaluation_must_cite_the_canonical_manifest(git_repo: Path, commit: Commit) -> None:
    evaluated = base(git_repo, commit)
    write_heldout(git_repo, DOCS, rel="artifacts/e0/other_manifest.json")
    commit(git_repo, "a manifest under another name")
    other = seeded_eval(
        perfect_items(DOCS), evaluated, heldout_manifest="artifacts/e0/other_manifest.json"
    )
    put(git_repo, EVAL, other)
    put(git_repo, "artifacts/e0/ledger_completeness.json", completeness())
    sha = commit(git_repo, "evaluate")
    with pytest.raises(GateError, match=r"does not cite artifacts/e0/heldout_manifest\.json"):
        ship_check.g5(context(git_repo, sha))


def test_a_dev_evaluation_committed_earlier_does_not_misdate_the_heldout_one(
    git_repo: Path, commit: Commit
) -> None:
    # Old code: git's --follow took the near-identical dev evaluation (committed before
    # the freeze) as the source of the held-out one, so a correct history FAILed.
    evaluated = base(git_repo, commit)
    put(
        git_repo,
        "artifacts/e0/seeded_eval_dev.json",
        seeded_eval(perfect_items(DOCS), evaluated, split="dev"),
    )
    commit(git_repo, "the development loop")
    write_heldout(git_repo, DOCS)
    commit(git_repo, "freeze the held-out half")
    put(git_repo, EVAL, seeded_eval(perfect_items(DOCS), evaluated))
    put(git_repo, "artifacts/e0/ledger_completeness.json", completeness())
    sha = commit(git_repo, "evaluate the held-out half")
    assert "ledger completeness 100%" in ship_check.g5(context(git_repo, sha))


def test_reports_committed_after_their_frozen_hashes_pass(git_repo: Path, commit: Commit) -> None:
    evaluated = base(git_repo, commit)
    write_heldout(git_repo, DOCS)
    for rid in DOCS:
        (git_repo / f"artifacts/e0/seeded/heldout/{rid}.json").unlink()
    commit(git_repo, "freeze the hashes only")
    write_reports(git_repo, DOCS)
    commit(git_repo, "add the byte-identical held-out reports")
    put(git_repo, EVAL, seeded_eval(perfect_items(DOCS), evaluated))
    put(git_repo, "artifacts/e0/ledger_completeness.json", completeness())
    sha = commit(git_repo, "evaluate")
    assert "ledger completeness 100%" in ship_check.g5(context(git_repo, sha))


def test_an_evaluation_renamed_into_place_after_the_freeze_fails(
    git_repo: Path, commit: Commit
) -> None:
    # Scored before the freeze under another name, then renamed after it.
    evaluated = base(git_repo, commit)
    put(git_repo, "artifacts/e0/early_scores.json", seeded_eval(perfect_items(DOCS), evaluated))
    commit(git_repo, "score first")
    write_heldout(git_repo, DOCS)
    commit(git_repo, "then freeze")
    (git_repo / "artifacts/e0/early_scores.json").rename(git_repo / EVAL)
    put(git_repo, "artifacts/e0/ledger_completeness.json", completeness())
    sha = commit(git_repo, "rename the early scores into place")
    with pytest.raises(GateError, match="not committed before the G5 evaluation"):
        ship_check.g5(context(git_repo, sha))


def test_first_added_follows_renames_but_not_copies(git_repo: Path, commit: Commit) -> None:
    body = "".join(f"SYNTHETIC line {n}\n" for n in range(40))
    put(git_repo, "a.txt", body)
    first = commit(git_repo, "add a")
    (git_repo / "a.txt").rename(git_repo / "b.txt")
    put(git_repo, "c.txt", body + "SYNTHETIC extra line\n")
    second = commit(git_repo, "rename a to b, copy it to c")
    found = ship_check.first_added(git_repo, ["b.txt", "c.txt", "gone.txt"])
    assert found == {"b.txt": first, "c.txt": second, "gone.txt": None}
    assert ship_check.first_exact_add(git_repo, "b.txt") == second


# ---------------------------------------------------------------- H14 (old code: PASS)


def test_a_report_left_out_of_the_items_fails(git_repo: Path, commit: Commit) -> None:
    # r2 went badly; its items are simply left out.
    ctx, _ = project(git_repo, commit, items=perfect_items({"r1": DOCS["r1"]}))
    with pytest.raises(GateError, match="differ from the frozen held-out gold"):
        ship_check.g5(ctx)


def test_relabeled_gold_verdicts_fail(git_repo: Path, commit: Commit) -> None:
    docs = {"r1": DOCS["r1"], "r2": doc("r2", gold(verdict="contradicted"))}
    items = perfect_items(docs)
    for item in items:
        item["gold_verdict"] = item["pred_verdict"] = "supported"
    ctx, _ = project(git_repo, commit, docs=docs, items=items)
    with pytest.raises(GateError, match="differ from the frozen held-out gold"):
        ship_check.g5(ctx)


def test_dropped_misses_fail(git_repo: Path, commit: Commit) -> None:
    # r2 keeps one correct item per type; its misses are dropped.
    items = perfect_items({"r1": DOCS["r1"]})
    items += [i for i in perfect_items({"r2": DOCS["r2"]})][:: len(gold()) // len(TYPES)]
    ctx, _ = project(git_repo, commit, items=items)
    with pytest.raises(GateError, match="differ from the frozen held-out gold"):
        ship_check.g5(ctx)


def test_a_report_with_no_gold_needs_no_items(git_repo: Path, commit: Commit) -> None:
    docs = {**DOCS, "r3": doc("r3", [])}
    ctx, _ = project(git_repo, commit, docs=docs)
    assert "ledger completeness 100%" in ship_check.g5(ctx)


IGNORED = [
    {"claim_id": f"x{n}", "claim_types": [ctype], "span": [9000 + 20 * n, 9010 + 20 * n]}
    for n, ctype in enumerate(t for t in TYPES for _ in range(3))
]


def ignored_items(claims: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """SYNTHETIC items for predictions matched to the ignored (disputed) claims."""
    return [
        {
            "report_id": "r1",
            "claim_type": c["claim_types"][0],
            "gold_verdict": None,
            "pred_verdict": "contradicted",
            "ignored": True,
            "ignored_claim_id": c["claim_id"],
            "pred_span": [c["span"][0] + 1, c["span"][1] - 1],
        }
        for c in claims
    ]


def test_predictions_on_frozen_ignored_claims_are_not_scored(
    git_repo: Path, commit: Commit
) -> None:
    # The harness half of H22: three disputed claims per type, each found; scored as
    # predictions they would cost precision (40/43 < 0.95), but adjudication dropped them.
    docs = {"r1": doc("r1", gold(), IGNORED), "r2": DOCS["r2"]}
    items = perfect_items(docs) + ignored_items(IGNORED)
    ctx, _ = project(git_repo, commit, docs=docs, items=items)
    assert "tests_pass P=1.000" in ship_check.g5(ctx)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"ignored_claim_id": "not-frozen"}, id="unknown-claim"),
        pytest.param({"pred_span": [1, 5]}, id="span-elsewhere"),
        pytest.param({"claim_type": "bug_fixed"}, id="other-type"),
        pytest.param({"gold_verdict": "supported"}, id="with-gold"),
    ],
)
def test_ignored_items_must_match_a_frozen_ignored_claim(
    git_repo: Path, commit: Commit, change: Mapping[str, Any]
) -> None:
    docs = {"r1": doc("r1", gold(), IGNORED[:1]), "r2": DOCS["r2"]}
    forged = ignored_items(IGNORED[:1])[0] | dict(change)
    ctx, _ = project(git_repo, commit, docs=docs, items=[*perfect_items(docs), forged])
    with pytest.raises(GateError, match="ignored"):
        ship_check.g5(ctx)


def test_an_ignored_claim_cannot_absorb_two_predictions(git_repo: Path, commit: Commit) -> None:
    docs = {"r1": doc("r1", gold(), IGNORED[:1]), "r2": DOCS["r2"]}
    twice = ignored_items(IGNORED[:1]) * 2
    ctx, _ = project(git_repo, commit, docs=docs, items=[*perfect_items(docs), *twice])
    with pytest.raises(GateError, match="ignored"):
        ship_check.g5(ctx)


# ---------------------------------------------------------------- H19 (old code: PASS)


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(
            [{"run_id": "anything", "transcript_commands": [], "ledger_commands": []}],
            id="unrelated-run-no-commands",
        ),
        pytest.param([{}], id="empty-row"),
        pytest.param(
            [{"run_id": r, "transcript": ["ls", "pytest -q"], "ledger": ["ls"]} for r in SMOKE_IDS],
            id="misspelled-keys",
        ),
        pytest.param(
            [{"run_id": SMOKE_IDS[0], "transcript_commands": ["ls"], "ledger_commands": ["ls"]}],
            id="one-of-five-runs",
        ),
        pytest.param(
            [{"run_id": r, "transcript_commands": [], "ledger_commands": []} for r in SMOKE_IDS],
            id="no-commands-at-all",
        ),
    ],
)
def test_vacuous_ledger_completeness_fails(
    git_repo: Path, commit: Commit, rows: list[dict[str, Any]]
) -> None:
    # The banked ledgers match each row's ledger_commands, so only the vacuity is wrong.
    commands = {str(r["run_id"]): r.get("ledger_commands", []) for r in rows if "run_id" in r}
    ctx, _ = project(git_repo, commit, completeness_rows=rows, commands=commands)
    with pytest.raises(GateError, match="ledger completeness"):
        ship_check.g5(ctx)


def test_a_validation_run_that_ran_no_command_is_allowed(git_repo: Path, commit: Commit) -> None:
    rows = completeness()["runs"]
    rows[0] = {"run_id": SMOKE_IDS[0], "transcript_commands": [], "ledger_commands": []}
    ctx, _ = project(git_repo, commit, completeness_rows=rows, commands={SMOKE_IDS[0]: ()})
    assert "ledger completeness 100% on 5 runs" in ship_check.g5(ctx)


def test_a_real_gap_still_fails(git_repo: Path, commit: Commit) -> None:
    rows = completeness()["runs"]
    rows[1] = {
        "run_id": SMOKE_IDS[1],
        "transcript_commands": ["ls", "pytest"],
        "ledger_commands": ["ls"],
    }
    ctx, _ = project(git_repo, commit, completeness_rows=rows, commands={SMOKE_IDS[1]: ["ls"]})
    with pytest.raises(GateError, match="1 command"):
        ship_check.g5(ctx)


def test_ledger_commands_must_be_what_the_banked_ledger_records(
    git_repo: Path, commit: Commit
) -> None:
    # A gap masked by listing a command the banked ledger never recorded.
    rows = completeness()["runs"]
    rows[1] = {
        "run_id": SMOKE_IDS[1],
        "transcript_commands": ["ls", "pytest"],
        "ledger_commands": ["ls", "pytest"],
    }
    ctx, _ = project(git_repo, commit, completeness_rows=rows, commands={SMOKE_IDS[1]: ["ls"]})
    with pytest.raises(GateError, match="ledger_commands are not the agent commands"):
        ship_check.g5(ctx)


def test_a_smoke_row_without_its_banked_run_fails(git_repo: Path, commit: Commit) -> None:
    project(git_repo, commit)
    for name in ("run.json", "ledger.jsonl", "transcript.json"):
        (git_repo / "artifacts/studies/smoke/runs" / SMOKE_IDS[2] / name).unlink()
    sha = commit(git_repo, "drop one banked smoke run")
    with pytest.raises(GateError, match=r"run\.json missing"):
        ship_check.g5(context(git_repo, sha))


# ---------------------------------------------------------------- H20 (old code: PASS)


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(
            {"run_id": "ref-replay", "task_id": "t0", "agent": "reference"}, id="reference-no-flag"
        ),
        pytest.param(
            {"run_id": "mock-1", "task_id": "t0", "agent": "mock", "synthetic": None},
            id="mock-null",
        ),
        pytest.param(
            {"run_id": "fix-1", "task_id": "t0", "agent": "fixture", "synthetic": False},
            id="fixture",
        ),
        pytest.param({"run_id": "anon-1", "task_id": "t0", "synthetic": 0}, id="no-agent"),
    ],
)
def test_rows_g6_rejects_cannot_source_the_counts(
    git_repo: Path, commit: Commit, row: dict[str, Any]
) -> None:
    run_ids = (*SMOKE_IDS, row["run_id"])
    counts = counts_artifact(labels=labels(COUNTS, run_ids), source_runs=[row["run_id"]])
    ctx, _ = project(git_repo, commit, counts=counts, extra_smoke=[row])
    with pytest.raises(GateError, match="real"):
        ship_check.g5(ctx)


# ---------------------------------------------------------------- H21 (old code: PASS)


def test_counts_from_the_extractor_under_test_fail(git_repo: Path, commit: Commit) -> None:
    extracted = {
        "source": "smoke-run final reports, pattern extractor",
        "counts": dict(COUNTS),
        "source_runs": list(SMOKE_IDS),
        "provenance": PROV,
    }
    ctx, _ = project(git_repo, commit, counts=extracted)
    with pytest.raises(GateError, match="blind labels"):
        ship_check.g5(ctx)


def missed_feature_claims() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """SYNTHETIC held-out reports with four feature_implemented claims, all missed."""
    extra = gold(per_type=4, types=("feature_implemented",))
    for n, claim in enumerate(extra):
        claim.update(claim_id=f"f{n}", span=[5000 + 10 * n, 5008 + 10 * n])
    docs = {"r1": doc("r1", gold() + extra), "r2": DOCS["r2"]}
    items = perfect_items(docs)
    for item in items:
        if item["claim_type"] == "feature_implemented":
            item["pred_verdict"] = None
    return docs, items


def test_counts_must_recompute_from_the_labels(git_repo: Path, commit: Commit) -> None:
    # The labels make feature_implemented common; hand-typed counts hide it from the top five.
    typed = counts_artifact(counts={**COUNTS, "feature_implemented": 1})
    typed["labels"] = labels({"feature_implemented": 12, **COUNTS})
    docs, items = missed_feature_claims()
    ctx, _ = project(git_repo, commit, counts=typed, docs=docs, items=items)
    with pytest.raises(GateError, match="do not recompute from the blind labels"):
        ship_check.g5(ctx)


def test_labels_must_cover_every_real_smoke_run(git_repo: Path, commit: Commit) -> None:
    partial = counts_artifact(labels=labels(COUNTS, SMOKE_IDS[:4]), source_runs=list(SMOKE_IDS[:4]))
    ctx, _ = project(git_repo, commit, counts=partial)
    with pytest.raises(GateError, match="blind labels cover"):
        ship_check.g5(ctx)


def test_labels_must_quote_the_banked_reports(git_repo: Path, commit: Commit) -> None:
    invented = counts_artifact()
    invented["labels"][0]["claims"].append({"type": "tests_pass", "text": "not in any report"})
    invented["counts"]["tests_pass"] += 1
    ctx, _ = project(git_repo, commit, counts=invented)
    with pytest.raises(GateError, match="not in its banked report"):
        ship_check.g5(ctx)


def test_the_most_common_labeled_type_is_gated(git_repo: Path, commit: Commit) -> None:
    # Blind labels make feature_implemented the most common type; the instrument misses
    # every held-out feature_implemented claim, so G5 must FAIL on it.
    counts = counts_artifact(counts={"feature_implemented": 12, **COUNTS})
    docs, items = missed_feature_claims()
    ctx, _ = project(git_repo, commit, counts=counts, docs=docs, items=items)
    with pytest.raises(GateError, match="feature_implemented"):
        ship_check.g5(ctx)


# ---------------------------------------------------------------- H23 (old code: PASS)


def test_an_instrument_change_after_the_evaluation_fails(git_repo: Path, commit: Commit) -> None:
    project(git_repo, commit)
    put(git_repo, "src/receipts/claims/patterns.py", "# SYNTHETIC stand-in, changed\nRULES = 2\n")
    sha = commit(git_repo, "change the extractor after the evaluation")
    with pytest.raises(GateError, match="instrument changed after the G5 evaluation"):
        ship_check.g5(context(git_repo, sha))


def test_an_unrelated_change_after_the_evaluation_passes(git_repo: Path, commit: Commit) -> None:
    project(git_repo, commit)
    put(git_repo, "README.md", "SYNTHETIC G5 test project, edited\n")
    sha = commit(git_repo, "edit the README")
    assert "ledger completeness 100%" in ship_check.g5(context(git_repo, sha))


@pytest.mark.parametrize("instrument", ["deadbeef", "0" * 40, ""], ids=["short", "zeros", "empty"])
def test_the_evaluated_instrument_must_be_a_commit(
    git_repo: Path, commit: Commit, instrument: str
) -> None:
    ctx, _ = project(git_repo, commit, instrument=instrument)
    with pytest.raises(GateError, match="instrument"):
        ship_check.g5(ctx)


def test_an_instrument_commit_outside_head_history_fails(git_repo: Path, commit: Commit) -> None:
    put(git_repo, "README.md", "SYNTHETIC side branch\n")
    side = commit(git_repo, "a commit HEAD will not contain")
    subprocess.run(["git", "-C", str(git_repo), "checkout", "-q", "--orphan", "fresh"], check=True)
    subprocess.run(["git", "-C", str(git_repo), "rm", "-rq", "--cached", "."], check=True)
    ctx, _ = project(git_repo, commit, instrument=side)
    with pytest.raises(GateError, match="not in HEAD's history"):
        ship_check.g5(ctx)


def test_an_evaluation_of_a_dirty_instrument_fails(git_repo: Path, commit: Commit) -> None:
    ctx, _ = project(git_repo, commit, dirty=True)
    with pytest.raises(GateError, match="uncommitted changes"):
        ship_check.g5(ctx)


def test_an_evaluation_without_an_instrument_record_fails(git_repo: Path, commit: Commit) -> None:
    project(git_repo, commit)
    data = json.loads((git_repo / EVAL).read_text(encoding="utf-8"))
    del data["instrument"]
    put(git_repo, EVAL, data)
    sha = commit(git_repo, "drop the instrument record")
    with pytest.raises(GateError, match="does not record the instrument"):
        ship_check.g5(context(git_repo, sha))


# ---------------------------------------------------------------- review-3 (old code: FAIL)


def edit_after_evaluation(root: Path, commit: Commit, rel: str) -> str:
    """Append a SYNTHETIC comment to ``rel`` in a commit after the evaluation."""
    put(root, rel, (root / rel).read_text(encoding="utf-8") + "# SYNTHETIC later edit\n")
    return commit(root, f"edit {rel} after the evaluation")


@pytest.mark.parametrize(
    "rel",
    [
        "src/receipts/evaluation/judges.py",
        "src/receipts/evaluation/e3.py",
        "src/receipts/evaluation/mechanism.py",
        "src/receipts/evaluation/completeness.py",
        "src/receipts/ledger/recorder.py",
        "src/receipts/__init__.py",
    ],
)
def test_code_the_scoring_never_loads_may_change_after_the_evaluation(
    git_repo: Path, commit: Commit, rel: str
) -> None:
    # Old code: any later change under src/receipts/evaluation or src/receipts/ledger
    # FAILed G5, so E2 or E3 work after the held-out evaluation could only be cleared by
    # scoring the single-use held-out reports again.
    project(git_repo, commit)
    sha = edit_after_evaluation(git_repo, commit, rel)
    assert "ledger completeness 100%" in ship_check.g5(context(git_repo, sha))


@pytest.mark.parametrize(
    "rel",
    [
        SEEDED,
        E0_MODULE,
        "src/receipts/evaluation/facts.py",
        "src/receipts/evaluation/__init__.py",
        "src/receipts/ledger/events.py",
        "src/receipts/ledger/__init__.py",
        CHECKERS,
        "src/receipts/claims/__init__.py",
    ],
)
def test_scoring_code_changed_after_the_evaluation_fails(
    git_repo: Path, commit: Commit, rel: str
) -> None:
    project(git_repo, commit)
    sha = edit_after_evaluation(git_repo, commit, rel)
    pattern = rf"instrument changed after the G5 evaluation at \w+: .*{re.escape(rel)}"
    with pytest.raises(GateError, match=pattern):
        ship_check.g5(context(git_repo, sha))


SPANS = "src/receipts/evaluation/spans.py"
BENCH_SPEC = "src/receipts/bench/spec.py"


def test_a_module_the_scorer_starts_to_import_is_bound(git_repo: Path, commit: Commit) -> None:
    # A helper module the scorer imports is part of the instrument, whatever its name.
    sources = {
        **INSTRUMENT,
        SEEDED: INSTRUMENT[SEEDED] + "from receipts.evaluation.spans import WIDTH\n",
        SPANS: "# SYNTHETIC span helper\nWIDTH = 1\n",
    }
    project(git_repo, commit, sources=sources)
    sha = edit_after_evaluation(git_repo, commit, SPANS)
    with pytest.raises(GateError, match=re.escape(SPANS)):
        ship_check.g5(context(git_repo, sha))


def lazy_bench_import() -> dict[str, str]:
    """The stand-ins with a verifier that loads a benchmark module inside a function."""
    lazy = (
        "\n\ndef requirements() -> int:\n"
        "    from receipts.bench.spec import TASKS\n\n"
        "    return TASKS\n"
    )
    return {
        **INSTRUMENT,
        CHECKERS: INSTRUMENT[CHECKERS] + lazy,
        "src/receipts/bench/__init__.py": "",
        BENCH_SPEC: "# SYNTHETIC benchmark spec\nTASKS = 1\n",
    }


def test_instrument_code_the_dirty_check_did_not_cover_fails(
    git_repo: Path, commit: Commit
) -> None:
    # Old code: PASS. The evaluation checked only CHECKED_PATHS for uncommitted changes,
    # so "dirty: false" says nothing about the benchmark module the verifier loads.
    ctx, _ = project(git_repo, commit, sources=lazy_bench_import())
    with pytest.raises(GateError, match=rf"uncommitted changes in .*{re.escape(BENCH_SPEC)}"):
        ship_check.g5(ctx)


def test_a_change_to_code_the_verifier_loads_fails(git_repo: Path, commit: Commit) -> None:
    # Old code: PASS. The verifier's behavior changed with src/receipts/bench/spec.py.
    paths = (*CHECKED_PATHS, "src/receipts/bench")
    project(git_repo, commit, sources=lazy_bench_import(), paths=paths)
    sha = edit_after_evaluation(git_repo, commit, BENCH_SPEC)
    with pytest.raises(GateError, match=re.escape(BENCH_SPEC)):
        ship_check.g5(context(git_repo, sha))


def test_an_instrument_without_the_e0_module_fails(git_repo: Path, commit: Commit) -> None:
    sources = {rel: text for rel, text in INSTRUMENT.items() if rel != E0_MODULE}
    ctx, _ = project(git_repo, commit, sources=sources)
    with pytest.raises(GateError, match=r"instrument is missing: receipts\.evaluation\.e0"):
        ship_check.g5(ctx)


def test_the_instrument_is_what_the_scoring_step_loads(tmp_path: Path) -> None:
    for rel, text in INSTRUMENT.items():
        put(tmp_path, rel, text)
    assert ship_check.instrument_files(tmp_path) == [
        "src/receipts/claims/__init__.py",
        "src/receipts/claims/patterns.py",
        "src/receipts/evaluation/__init__.py",
        E0_MODULE,
        "src/receipts/evaluation/facts.py",
        SEEDED,
        "src/receipts/ledger/__init__.py",
        "src/receipts/ledger/events.py",
        "src/receipts/verify/__init__.py",
        CHECKERS,
    ]


def test_imports_are_resolved_like_python_does() -> None:
    source = (
        "import os\n"
        "import receipts.ledger.events\n"
        "from . import patterns\n"
        "from ..verify import checkers\n"
        "if True:\n"
        "    from receipts.claims.types import Claim\n"
        "class Holder:\n"
        "    from receipts.evaluation import GOLD\n"
        "def later() -> None:\n"
        "    from receipts.bench.spec import TASKS\n"
    )
    loaded = {
        "receipts.ledger.events",
        "receipts.claims.patterns",
        "receipts.verify",
        "receipts.verify.checkers",
        "receipts.claims.types",
        "receipts.claims.types.Claim",
        "receipts.evaluation",
        "receipts.evaluation.GOLD",
    }
    # ``from . import x`` imports the package and, when x is a module, x.
    found = ship_check.imported_modules(source, "receipts.claims.extract", package=False)
    assert found == loaded | {"receipts.claims"}
    nested = ship_check.imported_modules(source, "receipts.claims", package=True, nested=True)
    assert "receipts.bench.spec" in nested and "receipts.claims.patterns" in nested
