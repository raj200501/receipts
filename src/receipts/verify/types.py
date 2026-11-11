"""Verdict types: the verifier's judgement of each claim against the ledger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from receipts.claims.types import Claim


class Label(StrEnum):
    """Outcome of checking one claim."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Verdict:
    """The verifier's judgement of one claim.

    Attributes:
        claim_id: The :class:`~receipts.claims.types.Claim` it judges.
        label: Supported, contradicted, or unverifiable.
        evidence: Sequence numbers of the ledger events the judgement rests on.
        reason: One plain sentence a user can read ("the last test run, after the
            final edit, had 1 failure: tests/test_io.py::test_roundtrip").
        checker: Name of the checker that produced it.
    """

    claim_id: str
    label: Label
    evidence: tuple[int, ...]
    reason: str
    checker: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable form."""
        return {
            "claim_id": self.claim_id,
            "label": self.label.value,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "checker": self.checker,
        }


@dataclass(frozen=True)
class Omission:
    """A known failure in the ledger that the report never mentions (RQ1).

    Attributes:
        kind: ``"failing_tests"``, ``"hidden_check_failed"``, ``"command_failed"``, or
            ``"unattainable_requirement"``.
        detail: What failed.
        evidence: Ledger event sequence numbers.
    """

    kind: str
    detail: str
    evidence: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable form."""
        return {"kind": self.kind, "detail": self.detail, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class RunVerification:
    """Everything receipts concluded about one run's final report.

    Attributes:
        claims: Extracted claims, in report order.
        verdicts: One verdict per claim, same order.
        success_reported: The report makes a non-negated success claim.
        ground_truth_success: Hidden checks all passed (None when there are none).
        false_success: ``success_reported and ground_truth_success is False``.
        omissions: Known failures the report never mentions.
    """

    claims: Sequence[Claim]
    verdicts: Sequence[Verdict]
    success_reported: bool
    ground_truth_success: bool | None
    omissions: Sequence[Omission] = field(default_factory=tuple)

    @property
    def false_success(self) -> bool:
        """True when the report claims success and the hidden checks say otherwise."""
        return self.success_reported and self.ground_truth_success is False

    def counts(self) -> Mapping[str, int]:
        """Number of verdicts per label."""
        out = {label.value: 0 for label in Label}
        for verdict in self.verdicts:
            out[verdict.label.value] += 1
        return out

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable form."""
        return {
            "claims": [c.to_dict() for c in self.claims],
            "verdicts": [v.to_dict() for v in self.verdicts],
            "success_reported": self.success_reported,
            "ground_truth_success": self.ground_truth_success,
            "false_success": self.false_success,
            "omissions": [o.to_dict() for o in self.omissions],
            "counts": dict(self.counts()),
        }
