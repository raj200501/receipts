"""Tests for the E0 extensions of seeded, completeness, facts, and the taxonomy constant.

Every ledger, transcript, and claim below is synthetic, hand-built for these tests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from receipts.claims.extract import extract_claims
from receipts.claims.types import ClaimType
from receipts.evaluation import CLAIM_TYPE_NAMES, GOLD_CLAIM_TYPES
from receipts.evaluation.completeness import check_run, task_start, transcript_commands
from receipts.evaluation.facts import fact_lines, fact_sheet
from receipts.evaluation.seeded import (
    GoldClaim,
    IgnoredClaim,
    PredictedClaim,
    TypeScore,
    match_claims,
    match_pairs,
    match_report,
    report_items,
    score,
)
from receipts.ledger.events import Ledger, LedgerWriter, sha256_text

ROOT = Path(__file__).resolve().parents[2]


def test_taxonomy_constant_equals_claim_type_values() -> None:
    assert len(set(CLAIM_TYPE_NAMES)) == len(CLAIM_TYPE_NAMES)
    assert set(CLAIM_TYPE_NAMES) == {t.value for t in ClaimType}
    assert tuple(n for n in CLAIM_TYPE_NAMES if n != "other") == GOLD_CLAIM_TYPES


def test_gold_types_are_the_rows_of_the_claim_types_page() -> None:
    text = (ROOT / "docs" / "CLAIM_TYPES.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([a-z_]+) \|", text, flags=re.M)
    assert rows == list(GOLD_CLAIM_TYPES)


def test_match_pairs_is_one_to_one_by_largest_overlap() -> None:
    gold = [
        GoldClaim("tests_pass", (0, 10), "supported", "g1"),
        GoldClaim("tests_pass", (8, 30), "contradicted", "g2"),
        GoldClaim("ran_command", (40, 50), "supported", "g3"),
    ]
    pred = [
        PredictedClaim("tests_pass", (9, 29), "contradicted", "c0"),
        PredictedClaim("ran_command", (0, 9), "supported", "c1"),
        PredictedClaim("tests_pass", (0, 9), "supported", "c2"),
    ]
    assert match_pairs(gold, pred) == {1: 0, 0: 2}
    items = match_report("r", gold, pred)
    assert [i["pred_verdict"] for i in items[:3]] == ["supported", "contradicted", None]
    assert items[3]["claim_type"] == "ran_command" and items[3]["gold_verdict"] is None
    assert GoldClaim("x", (0, 1), "supported").claim_id == ""


REPORT = "Updated `config.py` and `settings.py`."
KEPT = GoldClaim("file_modified", (0, 19), "supported", "g1", "Updated `config.py`")
DROPPED = IgnoredClaim(("file_modified",), (24, 37), "g2", "`settings.py`")


def test_a_prediction_on_a_dropped_claim_is_not_a_false_positive() -> None:
    # H22: adjudication dropped g2. A correct pipeline must still score P = R = 1.
    pred = [
        PredictedClaim("file_modified", (0, 38), "supported", "c0", "config.py"),
        PredictedClaim("file_modified", (0, 38), "contradicted", "c1", "settings.py"),
    ]
    matching = match_claims([KEPT], pred, [DROPPED])
    assert (dict(matching.gold), dict(matching.ignored)) == ({0: 0}, {0: 1})
    items = match_report("r", [KEPT], pred, ignored=[DROPPED])
    assert items == [
        {
            "report_id": "r",
            "claim_type": "file_modified",
            "gold_verdict": "supported",
            "pred_verdict": "supported",
        }
    ]
    scores = score(items)
    assert scores["file_modified"] == TypeScore("file_modified", 1, 1, 1)
    # Without the dropped claim, the second prediction is spurious (the H22 defect).
    assert score(match_report("r", [KEPT], pred))["file_modified"].precision == 0.5


def test_the_real_extractor_on_the_h22_sentence() -> None:
    claims = extract_claims(REPORT)
    assert [c.span for c in claims] == [(0, 38), (0, 38)]
    pred = [
        PredictedClaim(c.type.value, c.span, "supported", c.claim_id, str(c.params["path"]))
        for c in claims
    ]
    detail = report_items("r", [KEPT], pred, [DROPPED])
    assert score(detail)["file_modified"] == TypeScore("file_modified", 1, 1, 1, ignored=1)


def test_subject_agreement_breaks_ties_between_equal_overlaps() -> None:
    # Emission order reversed: span overlap alone would pair settings.py with config.py.
    pred = [
        PredictedClaim("file_modified", (0, 38), "contradicted", "c0", "settings.py"),
        PredictedClaim("file_modified", (0, 38), "supported", "c1", "config.py"),
    ]
    gold = [KEPT, GoldClaim("file_modified", (24, 37), "contradicted", "g2", "`settings.py`")]
    assert match_pairs(gold, pred) == {0: 1, 1: 0}
    assert all(i["pred_verdict"] == i["gold_verdict"] for i in match_report("r", gold, pred))
    no_subjects = [PredictedClaim(p.claim_type, p.span, p.verdict) for p in pred]
    assert match_pairs(gold, no_subjects) == {0: 0, 1: 1}


def test_ignored_claims_match_any_disputed_type_and_only_one_prediction() -> None:
    disputed = IgnoredClaim(("file_created", "file_modified"), (0, 20), "g9", "Added `notes.md`")
    pred = [
        PredictedClaim("file_created", (0, 20), "supported", "c0", "notes.md"),
        PredictedClaim("file_created", (0, 20), "supported", "c1", "notes.md"),
        PredictedClaim("tests_pass", (0, 20), "supported", "c2"),
    ]
    matching = match_claims([], pred, [disputed])
    assert dict(matching.ignored) == {0: 0} and dict(matching.gold) == {}
    items = match_report("r", [], pred, ignored=[disputed])
    # A second prediction on the same claim, and one of another type, stay spurious.
    assert [(i["claim_type"], i["gold_verdict"]) for i in items] == [
        ("file_created", None),
        ("tests_pass", None),
    ]


def test_an_ignored_claim_never_absorbs_a_prediction_of_another_type() -> None:
    # The only prediction on the disputed span has a type neither labeler gave it, so it
    # stays spurious instead of vanishing from precision.
    disputed = IgnoredClaim(("file_modified",), (0, 20), "g9", "Updated `notes.md`")
    pred = [PredictedClaim("tests_pass", (0, 20), "supported", "c0", "all")]
    assert dict(match_claims([], pred, [disputed]).ignored) == {}
    items = report_items("r", [], pred, [disputed])
    assert [(i["ignored"], i["claim_type"], i["pred_claim_id"]) for i in items] == [
        (True, "file_modified", None),
        (False, "tests_pass", "c0"),
    ]
    assert score(items)["tests_pass"] == TypeScore("tests_pass", 0, 1, 0)


def test_subject_agreement_decides_which_prediction_an_ignored_claim_absorbs() -> None:
    # "Updated `a.py` and `b.py`.": both predictions carry the whole sentence's span, and
    # only g2 ("`b.py`") is disputed. List order alone would give it the a.py prediction.
    disputed = IgnoredClaim(("file_modified",), (19, 25), "g2", "`b.py`")
    pred = [
        PredictedClaim("file_modified", (0, 26), "supported", "c0", "a.py"),
        PredictedClaim("file_modified", (0, 26), "contradicted", "c1", "b.py"),
    ]
    assert dict(match_claims([], pred, [disputed]).ignored) == {0: 1}
    items = report_items("r", [], pred, [disputed])
    assert [(i["ignored"], i["pred_subject"]) for i in items] == [(True, "b.py"), (False, "a.py")]


def test_gold_wins_a_tie_with_an_ignored_claim() -> None:
    gold = [GoldClaim("tests_pass", (0, 10), "supported", "g1", "tests pass")]
    ignored = [IgnoredClaim(("tests_pass",), (0, 10), "g2", "tests pass")]
    pred = [PredictedClaim("tests_pass", (0, 10), "supported", "c0")]
    matching = match_claims(gold, pred, ignored)
    assert dict(matching.gold) == {0: 0} and dict(matching.ignored) == {}
    assert matching.matched_predictions() == {0}


def test_report_items_record_ids_spans_and_ignored_claims() -> None:
    pred = [
        PredictedClaim("file_modified", (0, 38), "supported", "c0", "config.py"),
        PredictedClaim("file_modified", (0, 38), "contradicted", "c1", "settings.py"),
        PredictedClaim("ran_command", (40, 50), "supported", "c2", "ls"),
    ]
    unmatched = IgnoredClaim(("tests_pass", "test_count"), (60, 70), "g3", "all pass")
    items = report_items("r", [KEPT], pred, [DROPPED, unmatched])
    assert len(items) == 4
    keys = set(items[0])
    assert all(set(i) == keys for i in items)
    gold_item, ignored_item, empty_ignored, spurious = items
    assert gold_item == {
        "report_id": "r",
        "claim_type": "file_modified",
        "gold_verdict": "supported",
        "pred_verdict": "supported",
        "ignored": False,
        "gold_claim_id": "g1",
        "gold_span": [0, 19],
        "ignored_claim_id": None,
        "ignored_span": None,
        "ignored_types": None,
        "pred_claim_id": "c0",
        "pred_span": [0, 38],
        "pred_index": 0,
        "pred_subject": "config.py",
    }
    assert ignored_item["ignored"] is True and ignored_item["gold_verdict"] is None
    assert ignored_item["ignored_claim_id"] == "g2" and ignored_item["ignored_span"] == [24, 37]
    assert ignored_item["ignored_types"] == ["file_modified"]
    assert (ignored_item["pred_claim_id"], ignored_item["pred_verdict"]) == ("c1", "contradicted")
    assert empty_ignored["claim_type"] == "tests_pass" and empty_ignored["pred_verdict"] is None
    assert empty_ignored["pred_span"] is None and empty_ignored["pred_index"] is None
    assert spurious["gold_claim_id"] is None and spurious["pred_index"] == 2
    scores = score(items)
    assert scores["file_modified"] == TypeScore("file_modified", 1, 1, 1, ignored=1)
    assert scores["ran_command"] == TypeScore("ran_command", 0, 1, 0)
    assert scores["tests_pass"] == TypeScore("tests_pass", 0, 0, 0)


def test_report_items_reject_bad_verdicts_and_empty_ignored_types() -> None:
    with pytest.raises(ValueError, match="bad gold verdict"):
        report_items("r", [GoldClaim("x", (0, 1), "maybe")], [])
    with pytest.raises(ValueError, match="no type"):
        match_claims([], [], [IgnoredClaim((), (0, 1))])


def test_score_accepts_items_with_spans_and_ids() -> None:
    items: list[dict[str, object]] = [
        {
            "report_id": "r",
            "claim_type": "tests_pass",
            "gold_verdict": "supported",
            "pred_verdict": "supported",
            "gold_span": [0, 4],
            "pred_span": [1, 4],
        },
        {"report_id": "r", "claim_type": "tests_pass", "gold_verdict": None, "pred_verdict": "x"},
    ]
    scores = score(items)
    assert (scores["tests_pass"].correct, scores["tests_pass"].gold) == (1, 1)


def synthetic_ledger(tmp_path: Path) -> Ledger:
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    w.append(
        "run_start",
        {"run_id": "r1", "task_id": "t", "agent": "minimal-agent", "source": "harness"},
    )
    w.append("command", {"cmd": "cat <<EOF > a.txt\nhello\nEOF", "exit_code": 0, "source": "agent"})
    w.append("command", {"cmd": "ls", "exit_code": 0, "source": "agent"})
    w.append("run_end", {"final_report": "Done.", "turns": 2, "stop_reason": "finished"})
    return Ledger(w.events)


def test_fact_lines_are_the_fact_sheet_entries(tmp_path: Path) -> None:
    ledger = synthetic_ledger(tmp_path)
    lines = fact_lines(ledger)
    assert "\n".join(lines) + "\n" == fact_sheet(ledger)
    assert len(lines) == 4
    assert lines[1].startswith("[1] agent command `cat <<EOF > a.txt\nhello\nEOF` exit 0")
    assert lines[-1] == "Run ended: finished after 2 turns"
    assert all("Done." not in line for line in lines)


def act(tool: str, **args: str) -> dict[str, str]:
    return {"role": "assistant", "content": json.dumps({"tool": tool, "args": args})}


def obs(text: str) -> dict[str, str]:
    return {"role": "user", "content": text}


PROMPT = "Please fix the parser."
WITH_PRIOR_WORK = [
    {"role": "system", "content": "s"},
    obs("Earlier request."),
    act("bash", cmd="echo prior"),
    obs("Result of bash:\nprior\n[exit code 0]"),
    act("finish", report="Earlier work done."),
    obs(PROMPT),
    act("bash", cmd="ls"),
    obs("Result of bash:\na.py\n[exit code 0]"),
    act("run_tests"),
    obs("Result of run_tests:\n1 passed"),
]


def test_task_start_skips_prior_work(tmp_path: Path) -> None:
    start = task_start(WITH_PRIOR_WORK, sha256_text(PROMPT))
    assert start == 6
    assert transcript_commands(WITH_PRIOR_WORK, "pytest -q") == ["echo prior", "ls", "pytest -q"]
    assert transcript_commands(WITH_PRIOR_WORK, "pytest -q", start=start) == ["ls", "pytest -q"]
    w = LedgerWriter(tmp_path / "l.jsonl", clock=lambda: 1.0)
    w.append("command", {"cmd": "ls", "exit_code": 0, "source": "agent"})
    w.append("command", {"cmd": "pytest -q", "exit_code": 0, "source": "agent"})
    result = check_run("r1", WITH_PRIOR_WORK, Ledger(w.events), "pytest -q", start=start)
    assert result.missing == []


def test_task_start_uses_the_last_matching_request() -> None:
    messages = [obs(PROMPT), act("bash", cmd="echo a"), obs(PROMPT), act("bash", cmd="echo b")]
    assert task_start(messages, sha256_text(PROMPT)) == 3


def test_task_start_without_a_match() -> None:
    with pytest.raises(ValueError, match="prompt_sha256"):
        task_start(WITH_PRIOR_WORK, "0" * 64)
