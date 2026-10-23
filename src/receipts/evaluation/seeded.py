"""Scoring the extractor plus verifier against seeded reports (E0a, gate G5).

A seeded report is a synthetic final report written for a real ledger, with gold
claims: each gold claim has the exact span of its text in the report, a claim
type, and a gold verdict. Scoring matches the pipeline's claims to gold claims
and emits one *item* per gold claim and one per unmatched predicted claim, the
format ``tools/ship_check.py`` recomputes precision and recall from::

    {"report_id", "claim_type", "gold_verdict", "pred_verdict"}

Matching (one to one, greedy by overlap): a predicted claim matches a gold claim
of the same type when their character spans overlap. Larger overlaps are matched
first; ties go to the earlier gold claim. A gold claim with no match gets
``pred_verdict = None`` (a miss, counted against recall); a predicted claim with
no match gets ``gold_verdict = None`` (spurious, counted against precision).

Per claim type: precision = correct / predicted and recall = correct / gold,
where correct means matched with ``pred_verdict == gold_verdict``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

VERDICTS: frozenset[str] = frozenset({"supported", "contradicted", "unverifiable"})


@dataclass(frozen=True)
class GoldClaim:
    """One gold claim in a seeded report."""

    claim_type: str
    span: tuple[int, int]
    verdict: str


@dataclass(frozen=True)
class PredictedClaim:
    """One claim the pipeline extracted and judged."""

    claim_type: str
    span: tuple[int, int]
    verdict: str


def overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Number of characters two half-open spans share."""
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def match_report(
    report_id: str, gold: Sequence[GoldClaim], predicted: Sequence[PredictedClaim]
) -> list[dict[str, str | None]]:
    """Return the scoring items for one report."""
    for claim in gold:
        if claim.verdict not in VERDICTS:
            raise ValueError(f"{report_id}: bad gold verdict {claim.verdict!r}")
    pairs = sorted(
        (
            (-overlap(g.span, p.span), gi, pi)
            for gi, g in enumerate(gold)
            for pi, p in enumerate(predicted)
            if g.claim_type == p.claim_type and overlap(g.span, p.span) > 0
        ),
    )
    gold_to_pred: dict[int, int] = {}
    used_pred: set[int] = set()
    for _, gi, pi in pairs:
        if gi in gold_to_pred or pi in used_pred:
            continue
        gold_to_pred[gi] = pi
        used_pred.add(pi)
    items: list[dict[str, str | None]] = []
    for gi, g in enumerate(gold):
        matched = gold_to_pred.get(gi)
        items.append(
            {
                "report_id": report_id,
                "claim_type": g.claim_type,
                "gold_verdict": g.verdict,
                "pred_verdict": None if matched is None else predicted[matched].verdict,
            }
        )
    for pi, p in enumerate(predicted):
        if pi not in used_pred:
            items.append(
                {
                    "report_id": report_id,
                    "claim_type": p.claim_type,
                    "gold_verdict": None,
                    "pred_verdict": p.verdict,
                }
            )
    return items


@dataclass(frozen=True)
class TypeScore:
    """Precision and recall for one claim type, with Wilson 95% intervals."""

    claim_type: str
    correct: int
    predicted: int
    gold: int

    @property
    def precision(self) -> float:
        """correct / predicted (NaN when nothing was predicted)."""
        return self.correct / self.predicted if self.predicted else math.nan

    @property
    def recall(self) -> float:
        """correct / gold (NaN when there is no gold claim)."""
        return self.correct / self.gold if self.gold else math.nan

    def precision_ci(self) -> tuple[float, float]:
        """Wilson 95% interval for precision."""
        return wilson(self.correct, self.predicted)

    def recall_ci(self) -> tuple[float, float]:
        """Wilson 95% interval for recall."""
        return wilson(self.correct, self.gold)


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval (identical to the one ship_check uses)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def score(items: Iterable[Mapping[str, str | None]]) -> dict[str, TypeScore]:
    """Per-type scores from scoring items."""
    tallies: dict[str, list[int]] = {}
    for item in items:
        ctype = str(item["claim_type"])
        tally = tallies.setdefault(ctype, [0, 0, 0])
        gold, pred = item.get("gold_verdict"), item.get("pred_verdict")
        if pred in VERDICTS:
            tally[1] += 1
        if gold in VERDICTS:
            tally[2] += 1
            if pred == gold:
                tally[0] += 1
    return {t: TypeScore(t, c, p, g) for t, (c, p, g) in sorted(tallies.items())}
