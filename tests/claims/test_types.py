"""Tests for the receipts.claims.types contract as the extractors use it (hand-written data)."""

from __future__ import annotations

import json

import pytest

from receipts.claims import extract_claims
from receipts.claims.types import SUCCESS_TYPES, Claim, ClaimType


def test_extracted_claims_round_trip_through_json() -> None:
    report = "Fixed the race in `queue.py`. All 12 tests pass. I did not run the linter."
    for claim in extract_claims(report):
        data = json.loads(json.dumps(claim.to_dict()))
        assert Claim.from_dict(data) == claim


def test_from_dict_defaults_and_param_coercion() -> None:
    claim = Claim.from_dict(
        {
            "claim_id": "c3",
            "type": "test_count",
            "text": "12 passed",
            "span": [4, 13],
            "params": {"passed": 12, "flaky": True, "ratio": 0.5, "scope": None},
        }
    )
    assert claim.extractor == "pattern" and claim.negated is False
    assert dict(claim.params) == {"passed": 12, "flaky": "true", "ratio": "0.5", "scope": None}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"type": "other", "text": "x", "span": [0, 1]}, "claim missing"),
        ({"claim_id": "c0", "type": "other", "text": "x", "span": [0]}, "span must be a pair"),
        (
            {"claim_id": "c0", "type": "other", "text": "x", "span": [0, 1], "params": []},
            "params must be an object",
        ),
        (
            {"claim_id": "c0", "type": "other", "text": "x", "span": [0, 1], "extractor": "x"},
            "unknown extractor",
        ),
    ],
)
def test_from_dict_rejects_malformed_input(data: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Claim.from_dict(data)


def test_success_types_are_claim_types() -> None:
    assert set(ClaimType) >= SUCCESS_TYPES
    assert ClaimType.TEST_COUNT in SUCCESS_TYPES
    assert ClaimType.COULD_NOT not in SUCCESS_TYPES
