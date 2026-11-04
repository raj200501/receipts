"""Extract every claim from a final report: pattern rules first, then optionally a model.

:func:`extract_claims` splits the report into claim-bearing units
(:mod:`receipts.claims.segment`), runs the deterministic pattern rules on every unit
(:mod:`receipts.claims.patterns`), and, when a :class:`~receipts.claims.model.
ModelExtractor` is given, asks it only about the units in which no pattern rule found a
claim. Without a model the result is fully deterministic and needs no network.
"""

from __future__ import annotations

from dataclasses import replace

from receipts.claims.model import ModelExtractor
from receipts.claims.patterns import hit_claim, match_units
from receipts.claims.segment import Unit, segment
from receipts.claims.types import Claim


def extract_claims(report: str, *, model: ModelExtractor | None = None) -> list[Claim]:
    """Every claim in ``report``, in report order, with ids ``"c0"``, ``"c1"``, ...

    Pattern claims (extractor ``"pattern"``) come from every unit; claims of one unit
    with identical (type, params) are kept once. With ``model``, the units that yielded
    no pattern claim are sent to it, and its claims (extractor ``"model"``) are merged
    in. Claims are ordered by where they start in the report, and claims of one unit
    keep the order the rules found them in. Exceptions raised by the model's
    ``complete`` callable propagate.
    """
    claims: list[Claim] = []
    uncovered: list[Unit] = []
    for matches in match_units(segment(report)):
        if not matches.hits:
            uncovered.append(matches.unit)
        claims.extend(hit_claim(matches.unit, hit, "") for hit in matches.hits)
    if model is not None and uncovered:
        claims.extend(model.extract(report, uncovered))
    claims.sort(key=lambda claim: claim.span[0])
    return [replace(claim, claim_id=f"c{index}") for index, claim in enumerate(claims)]
