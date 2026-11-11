"""The development corpus: hand-written reports that the pattern extractor must recover.

tests/fixtures/claims/dev_reports.json holds hand-written, synthetic final reports (labeled
as development fixtures, not evaluation data). For each report, ``expected`` lists the
claims the pattern extractor must produce, exactly; ``model_only`` lists claims a reader
would also extract that no pattern rule targets.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from receipts.claims import extract_claims
from receipts.claims.model import PARAM_SPECS, REQUIRED_PARAMS
from receipts.claims.types import ClaimType

CORPUS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "claims" / "dev_reports.json"
CORPUS: dict[str, Any] = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
REPORTS: list[dict[str, Any]] = CORPUS["reports"]
STYLES = {"claude-code", "codex", "aider", "openhands", "minimal-agent"}

Key = tuple[str, tuple[tuple[str, object], ...], bool]


def key(claim_type: str, params: dict[str, object], negated: bool) -> Key:
    return (claim_type, tuple(sorted(params.items())), negated)


def pattern_keys(text: str) -> Counter[Key]:
    return Counter(key(c.type.value, dict(c.params), c.negated) for c in extract_claims(text))


def test_corpus_is_labeled_as_hand_written_development_data() -> None:
    assert CORPUS["synthetic"] is True
    assert CORPUS["label"] == "hand-written development fixtures"
    assert "not evaluation data" in CORPUS["description"]
    assert len(REPORTS) >= 60
    assert len({r["id"] for r in REPORTS}) == len(REPORTS)
    assert {r["style"] for r in REPORTS} == STYLES


def test_corpus_labels_are_well_formed() -> None:
    for entry in REPORTS:
        assert entry["report"].strip(), entry["id"]
        for claim in entry["expected"] + entry["model_only"]:
            claim_type = ClaimType(claim["type"])
            assert set(claim["params"]) <= set(PARAM_SPECS[claim_type]), (entry["id"], claim)
            if claim in entry["expected"]:
                required = REQUIRED_PARAMS.get(claim_type, frozenset())
                assert required <= set(claim["params"]), (entry["id"], claim)
            assert isinstance(claim["negated"], bool)


def test_corpus_covers_every_claim_type_but_other() -> None:
    seen = {c["type"] for r in REPORTS for c in r["expected"]}
    assert seen == {t.value for t in ClaimType} - {"other"}


@pytest.mark.parametrize("entry", REPORTS, ids=[r["id"] for r in REPORTS])
def test_patterns_recover_each_report(entry: dict[str, Any]) -> None:
    got = pattern_keys(entry["report"])
    want = Counter(key(c["type"], c["params"], c["negated"]) for c in entry["expected"])
    assert got == want, {"extra": sorted(got - want), "missing": sorted(want - got)}


@pytest.mark.parametrize("entry", REPORTS, ids=[r["id"] for r in REPORTS])
def test_model_only_claims_are_not_pattern_claims(entry: dict[str, Any]) -> None:
    got = pattern_keys(entry["report"])
    for claim in entry["model_only"]:
        assert key(claim["type"], claim["params"], claim["negated"]) not in got


def test_every_claim_text_is_its_span() -> None:
    for entry in REPORTS:
        text = entry["report"]
        ids = []
        for claim in extract_claims(text):
            assert text[claim.span[0] : claim.span[1]] == claim.text
            assert claim.extractor == "pattern"
            ids.append(claim.claim_id)
        assert ids == [f"c{i}" for i in range(len(ids))]
