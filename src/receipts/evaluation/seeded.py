"""Scoring the extractor plus verifier against seeded reports (E0a, gate G5).

A seeded report is a synthetic final report written for a real ledger, with gold
claims: each gold claim has the exact span of its text in the report, a claim
type, and a gold verdict. Claims on which the writer and the adjudicator disagreed
are not gold; they are kept as *ignored* claims (:class:`IgnoredClaim`) so that a
correct extraction of one of them is neither credited nor counted as spurious.
Scoring matches the pipeline's claims to gold and ignored claims and emits one
*item* per gold claim and one per predicted claim matched to nothing, the format
``tools/ship_check.py`` recomputes precision and recall from::

    {"report_id", "claim_type", "gold_verdict", "pred_verdict"}

:func:`report_items` adds ids, spans, subjects, and one item per ignored claim
(``"ignored": true``) so the matching can be recomputed from the held-out files.

Matching (:func:`match_claims`, one to one, greedy): a predicted claim can match a
gold claim of the same type, or an ignored claim with that type among its disputed
types, when their character spans overlap. Larger overlaps are matched first; ties
go to pairs where the predicted claim's subject (its path, command, dependency name,
or description) appears in the claim's text, then to gold claims before ignored
ones, then to the earlier claim, then to the earlier prediction. A gold claim with
no match gets ``pred_verdict = None`` (a miss, counted against recall); a predicted
claim matched to nothing gets ``gold_verdict = None`` (spurious, counted against
precision); a predicted claim matched to an ignored claim is left out of scoring.

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
    """One gold claim in a seeded report.

    ``claim_id`` is for traceability. ``text`` (the claim's verbatim words in the
    report) breaks ties in matching; both are optional.
    """

    claim_type: str
    span: tuple[int, int]
    verdict: str
    claim_id: str = ""
    text: str = ""


@dataclass(frozen=True)
class IgnoredClaim:
    """A claim dropped from the gold set because the writer and the adjudicator disagreed.

    Its type or truth is in dispute, so a predicted claim matched to it is neither
    correct nor spurious and is left out of scoring. ``claim_types`` holds every type
    either labeler gave it (one type when they agreed on the type but not the truth).
    """

    claim_types: tuple[str, ...]
    span: tuple[int, int]
    claim_id: str = ""
    text: str = ""


@dataclass(frozen=True)
class PredictedClaim:
    """One claim the pipeline extracted and judged.

    ``claim_id`` is optional. ``subject`` (what the claim is about: its path, command,
    dependency name, or description) breaks ties in matching.
    """

    claim_type: str
    span: tuple[int, int]
    verdict: str
    claim_id: str = ""
    subject: str = ""


@dataclass(frozen=True)
class Matching:
    """Which predicted claim each gold and each ignored claim was matched to (by index)."""

    gold: Mapping[int, int]
    ignored: Mapping[int, int]

    def matched_predictions(self) -> set[int]:
        """Indices of the predicted claims matched to a gold or an ignored claim."""
        return set(self.gold.values()) | set(self.ignored.values())


def overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Number of characters two half-open spans share."""
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def agrees(text: str, subject: str) -> bool:
    """True when a predicted claim's subject appears verbatim in a claim's text."""
    return bool(subject) and subject in text


def match_claims(
    gold: Sequence[GoldClaim],
    predicted: Sequence[PredictedClaim],
    ignored: Sequence[IgnoredClaim] = (),
) -> Matching:
    """Match predicted claims one to one against gold and ignored claims together.

    A (claim, prediction) pair is a candidate when the prediction's type is the gold
    claim's type, or one of the ignored claim's types, and their spans overlap.
    Candidates are taken greedily, sorted by: larger overlap; then subject agreement
    (:func:`agrees`); then gold before ignored; then claim index; then prediction index.
    Raises ValueError for an ignored claim with no type.
    """
    candidates: list[tuple[int, int, int, int, int]] = []
    for gi, g in enumerate(gold):
        for pi, p in enumerate(predicted):
            shared = overlap(g.span, p.span)
            if p.claim_type == g.claim_type and shared > 0:
                candidates.append((-shared, 0 if agrees(g.text, p.subject) else 1, 0, gi, pi))
    for ii, c in enumerate(ignored):
        if not c.claim_types:
            raise ValueError(f"ignored claim {c.claim_id or ii} has no type")
        for pi, p in enumerate(predicted):
            shared = overlap(c.span, p.span)
            if p.claim_type in c.claim_types and shared > 0:
                candidates.append((-shared, 0 if agrees(c.text, p.subject) else 1, 1, ii, pi))
    taken: tuple[dict[int, int], dict[int, int]] = ({}, {})
    used_pred: set[int] = set()
    for _, _, kind, index, pi in sorted(candidates):
        if index in taken[kind] or pi in used_pred:
            continue
        taken[kind][index] = pi
        used_pred.add(pi)
    return Matching(gold=taken[0], ignored=taken[1])


def match_pairs(gold: Sequence[GoldClaim], predicted: Sequence[PredictedClaim]) -> dict[int, int]:
    """``{gold index: predicted index}`` from :func:`match_claims` with no ignored claims."""
    return dict(match_claims(gold, predicted).gold)


def _check_gold(report_id: str, gold: Sequence[GoldClaim]) -> None:
    for claim in gold:
        if claim.verdict not in VERDICTS:
            raise ValueError(f"{report_id}: bad gold verdict {claim.verdict!r}")


def match_report(
    report_id: str,
    gold: Sequence[GoldClaim],
    predicted: Sequence[PredictedClaim],
    *,
    ignored: Sequence[IgnoredClaim] = (),
) -> list[dict[str, str | None]]:
    """Return the four-key scoring items for one report (matching by :func:`match_claims`).

    One item per gold claim, then one per predicted claim matched to nothing; a
    predicted claim matched to an ignored claim yields no item.
    """
    _check_gold(report_id, gold)
    matching = match_claims(gold, predicted, ignored)
    items: list[dict[str, str | None]] = []
    for gi, g in enumerate(gold):
        matched = matching.gold.get(gi)
        items.append(
            {
                "report_id": report_id,
                "claim_type": g.claim_type,
                "gold_verdict": g.verdict,
                "pred_verdict": None if matched is None else predicted[matched].verdict,
            }
        )
    used = matching.matched_predictions()
    for pi, p in enumerate(predicted):
        if pi not in used:
            items.append(
                {
                    "report_id": report_id,
                    "claim_type": p.claim_type,
                    "gold_verdict": None,
                    "pred_verdict": p.verdict,
                }
            )
    return items


def _item(
    report_id: str,
    claim_type: str,
    pred: PredictedClaim | None,
    pi: int | None,
    *,
    gold: GoldClaim | None = None,
    ignored: IgnoredClaim | None = None,
) -> dict[str, object]:
    return {
        "report_id": report_id,
        "claim_type": claim_type,
        "gold_verdict": None if gold is None else gold.verdict,
        "pred_verdict": None if pred is None else pred.verdict,
        "ignored": ignored is not None,
        "gold_claim_id": None if gold is None else gold.claim_id,
        "gold_span": None if gold is None else list(gold.span),
        "ignored_claim_id": None if ignored is None else ignored.claim_id,
        "ignored_span": None if ignored is None else list(ignored.span),
        "ignored_types": None if ignored is None else list(ignored.claim_types),
        "pred_claim_id": None if pred is None else pred.claim_id,
        "pred_span": None if pred is None else list(pred.span),
        "pred_index": pi,
        "pred_subject": None if pred is None else pred.subject,
    }


def report_items(
    report_id: str,
    gold: Sequence[GoldClaim],
    predicted: Sequence[PredictedClaim],
    ignored: Sequence[IgnoredClaim] = (),
) -> list[dict[str, object]]:
    """Return the detailed scoring items for one report (``artifacts/e0/seeded_eval.json``).

    One item per gold claim, then one per ignored claim (``"ignored": true``, with the
    prediction matched to it, if any, and ``gold_verdict`` None), then one per predicted
    claim matched to nothing. Every item has the same keys: the four scoring keys,
    ``ignored``, the gold claim's id and span, the ignored claim's id, span, and types,
    and the prediction's id, span, index (its position in extraction order), and
    subject; keys that do not apply are None. :func:`score` skips ignored items.
    """
    _check_gold(report_id, gold)
    matching = match_claims(gold, predicted, ignored)
    items: list[dict[str, object]] = []
    for gi, g in enumerate(gold):
        pi = matching.gold.get(gi)
        pred = None if pi is None else predicted[pi]
        items.append(_item(report_id, g.claim_type, pred, pi, gold=g))
    for ii, c in enumerate(ignored):
        pi = matching.ignored.get(ii)
        pred = None if pi is None else predicted[pi]
        ctype = c.claim_types[0] if pred is None else pred.claim_type
        items.append(_item(report_id, ctype, pred, pi, ignored=c))
    used = matching.matched_predictions()
    for pi, p in enumerate(predicted):
        if pi not in used:
            items.append(_item(report_id, p.claim_type, p, pi))
    return items


@dataclass(frozen=True)
class TypeScore:
    """Precision and recall for one claim type, with Wilson 95% intervals.

    ``ignored`` counts predictions matched to ignored claims (left out of both rates).
    """

    claim_type: str
    correct: int
    predicted: int
    gold: int
    ignored: int = 0

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


def score(items: Iterable[Mapping[str, object]]) -> dict[str, TypeScore]:
    """Per-type scores from scoring items (extra keys such as ids and spans are ignored).

    Items marked ``"ignored": true`` count only toward :attr:`TypeScore.ignored`.
    """
    tallies: dict[str, list[int]] = {}
    for item in items:
        ctype = str(item["claim_type"])
        tally = tallies.setdefault(ctype, [0, 0, 0, 0])
        gold, pred = item.get("gold_verdict"), item.get("pred_verdict")
        if item.get("ignored") is True:
            if pred in VERDICTS:
                tally[3] += 1
            continue
        if pred in VERDICTS:
            tally[1] += 1
        if gold in VERDICTS:
            tally[2] += 1
            if pred == gold:
                tally[0] += 1
    return {t: TypeScore(t, c, p, g, i) for t, (c, p, g, i) in sorted(tallies.items())}
