"""Tests for receipts.claims.extract. Reports and model replies here are hand-written fakes."""

from __future__ import annotations

import json
import re

import pytest

import receipts.claims as claims_pkg
from receipts.claims import ModelExtractor, extract_claims
from receipts.claims.types import ClaimType

# Hand-written test input (synthetic), not model output.
REPORT = """I wired the retry logic into the HTTP client.

- Updated `src/http/client.py`.
- The backoff is capped at 30 seconds.

All 12 tests pass and ruff is clean.
"""


def test_pattern_claims_in_report_order_with_fresh_ids() -> None:
    claims = extract_claims(REPORT)
    assert [(c.claim_id, c.type, c.extractor) for c in claims] == [
        ("c0", ClaimType.FILE_MODIFIED, "pattern"),
        ("c1", ClaimType.TEST_COUNT, "pattern"),
        ("c2", ClaimType.LINT_CLEAN, "pattern"),
    ]
    for claim in claims:
        assert REPORT[claim.span[0] : claim.span[1]] == claim.text


def test_empty_and_claimless_reports() -> None:
    assert extract_claims("") == []
    assert extract_claims("Hello! Let me know if you need anything else.") == []


def test_model_is_asked_only_about_units_without_pattern_claims() -> None:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "claims": [
                    {
                        "passage": 1,
                        "type": "feature_implemented",
                        "text": "I wired the retry logic into the HTTP client.",
                        "params": {"description": "the retry logic"},
                        "negated": False,
                    },
                    {
                        "passage": 2,
                        "type": "other",
                        "text": "The backoff is capped at 30 seconds.",
                        "params": {"description": "backoff capped at 30 seconds"},
                        "negated": False,
                    },
                    {  # a unit the patterns already cover: dropped
                        "passage": 1,
                        "type": "tests_pass",
                        "text": "All 12 tests pass",
                        "params": {},
                        "negated": False,
                    },
                ]
            }
        )

    claims = extract_claims(REPORT, model=ModelExtractor(complete))
    assert len(prompts) == 1
    assert "P1: I wired the retry logic into the HTTP client." in prompts[0]
    assert "P2: The backoff is capped at 30 seconds." in prompts[0]
    assert "P3:" not in prompts[0]
    assert [(c.claim_id, c.type, c.extractor) for c in claims] == [
        ("c0", ClaimType.FEATURE_IMPLEMENTED, "model"),
        ("c1", ClaimType.FILE_MODIFIED, "pattern"),
        ("c2", ClaimType.OTHER, "model"),
        ("c3", ClaimType.TEST_COUNT, "pattern"),
        ("c4", ClaimType.LINT_CLEAN, "pattern"),
    ]


def test_model_never_sees_headings_labels_or_unchecked_items() -> None:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"claims": []})

    report = "## Plan\n\n**Open items:**\n\n- [ ] Wire the cache\n- [x] Wrote the notes\n"
    assert extract_claims(report, model=ModelExtractor(complete)) == []
    (prompt,) = prompts
    passages = [line for line in prompt.splitlines() if re.match(r"P\d+: ", line)]
    assert passages == ["P1: Wrote the notes"]


def test_model_is_not_called_when_patterns_cover_every_unit() -> None:
    def complete(prompt: str) -> str:
        raise AssertionError("the model must not be called")

    claims = extract_claims("Done. All tests pass.", model=ModelExtractor(complete))
    assert [c.type for c in claims] == [ClaimType.TASK_COMPLETE, ClaimType.TESTS_PASS]


def test_model_errors_propagate() -> None:
    def complete(prompt: str) -> str:
        raise ConnectionError("no model")

    with pytest.raises(ConnectionError):
        extract_claims(REPORT, model=ModelExtractor(complete))


def test_package_exports_the_api() -> None:
    assert claims_pkg.extract_claims is extract_claims
    for name in claims_pkg.__all__:
        assert hasattr(claims_pkg, name)
