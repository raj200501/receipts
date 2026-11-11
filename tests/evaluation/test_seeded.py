"""Tests for seeded-report scoring (all claims below are synthetic)."""

from __future__ import annotations

import math

import pytest

from receipts.evaluation.seeded import (
    GoldClaim,
    PredictedClaim,
    TypeScore,
    match_report,
    overlap,
    score,
    wilson,
)


def test_overlap() -> None:
    assert overlap((0, 10), (5, 20)) == 5
    assert overlap((0, 5), (5, 9)) == 0
    assert overlap((3, 4), (0, 10)) == 1


def test_match_correct_wrong_missed_spurious() -> None:
    gold = [
        GoldClaim("tests_pass", (0, 20), "contradicted"),
        GoldClaim("file_modified", (21, 40), "supported"),
        GoldClaim("ran_command", (41, 60), "supported"),
    ]
    pred = [
        PredictedClaim("tests_pass", (2, 18), "contradicted"),
        PredictedClaim("file_modified", (25, 35), "unverifiable"),
        PredictedClaim("dependency_added", (61, 70), "supported"),
        PredictedClaim("ran_command", (0, 5), "supported"),
    ]
    items = match_report("r1", gold, pred)
    assert [i["pred_verdict"] for i in items[:3]] == ["contradicted", "unverifiable", None]
    assert items[3] == {
        "report_id": "r1",
        "claim_type": "dependency_added",
        "gold_verdict": None,
        "pred_verdict": "supported",
    }
    assert items[4]["claim_type"] == "ran_command" and items[4]["gold_verdict"] is None
    scores = score(items)
    assert scores["tests_pass"] == TypeScore("tests_pass", 1, 1, 1)
    assert scores["file_modified"].precision == 0.0 and scores["file_modified"].recall == 0.0
    assert scores["ran_command"].recall == 0.0 and scores["ran_command"].precision == 0.0
    assert math.isnan(scores["dependency_added"].recall)


def test_one_to_one_by_largest_overlap() -> None:
    gold = [
        GoldClaim("tests_pass", (0, 10), "supported"),
        GoldClaim("tests_pass", (8, 30), "contradicted"),
    ]
    pred = [PredictedClaim("tests_pass", (9, 29), "contradicted")]
    items = match_report("r", gold, pred)
    assert items[0]["pred_verdict"] is None and items[1]["pred_verdict"] == "contradicted"


def test_bad_gold_verdict() -> None:
    with pytest.raises(ValueError, match="bad gold verdict"):
        match_report("r", [GoldClaim("x", (0, 1), "maybe")], [])


def test_wilson_and_nan_scores() -> None:
    lo, hi = wilson(19, 20)
    assert lo < 0.95 < hi
    assert wilson(0, 0) == (0.0, 1.0)
    empty = TypeScore("x", 0, 0, 0)
    assert math.isnan(empty.precision) and empty.precision_ci() == (0.0, 1.0)
    assert TypeScore("x", 9, 10, 10).recall_ci()[0] > 0.5
