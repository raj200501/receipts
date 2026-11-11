"""Claim types: the atomic statements extracted from an agent's final report.

A :class:`Claim` is one checkable statement ("I ran the tests", "all 12 tests
pass", "updated config.py"). Extractors (deterministic patterns first, then a
model extractor with a strict JSON schema for the rest) turn a report into
claims; :mod:`receipts.verify` checks each claim against the ledger.

``params`` carries the claim's arguments with these keys per type (all optional
unless noted):

=====================  ==============================================================
type                   params
=====================  ==============================================================
tests_pass             scope (e.g. "all", "unit", a path)
test_count             passed (int), total (int), failed (int)
tests_added            path, target (what the tests cover)
ran_command            command (required): the command as written in the report
file_modified          path (required)
file_created           path (required)
file_deleted           path (required)
file_unchanged         path (required): "did not touch X"
dependency_added       name (required), version
dependency_updated     name (required), version (the new one)
dependency_removed     name (required)
bug_fixed              description (required)
feature_implemented    description (required)
lint_clean             tool
typecheck_clean        tool
build_succeeds         tool
could_not              description (required): what the agent says it could not do
task_complete          (none): "Done", "everything is implemented", "all set"
other                  description
=====================  ==============================================================

``negated`` marks a claim stated in the negative ("the tests do not pass yet",
"I did not run the linter"). A negated claim is an admission: it is supported
when the ledger agrees that the thing did not happen or did not succeed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, cast

ParamValue = str | int | None


class ClaimType(StrEnum):
    """Every claim type receipts knows how to extract."""

    TESTS_PASS = "tests_pass"
    TEST_COUNT = "test_count"
    TESTS_ADDED = "tests_added"
    RAN_COMMAND = "ran_command"
    FILE_MODIFIED = "file_modified"
    FILE_CREATED = "file_created"
    FILE_DELETED = "file_deleted"
    FILE_UNCHANGED = "file_unchanged"
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_UPDATED = "dependency_updated"
    DEPENDENCY_REMOVED = "dependency_removed"
    BUG_FIXED = "bug_fixed"
    FEATURE_IMPLEMENTED = "feature_implemented"
    LINT_CLEAN = "lint_clean"
    TYPECHECK_CLEAN = "typecheck_clean"
    BUILD_SUCCEEDS = "build_succeeds"
    COULD_NOT = "could_not"
    TASK_COMPLETE = "task_complete"
    OTHER = "other"


#: Claim types whose truth implies the task (or a part of it) succeeded. A report
#: containing a non-negated claim of one of these types is a success report for the
#: false-success rate (RQ1).
SUCCESS_TYPES: frozenset[ClaimType] = frozenset(
    {
        ClaimType.TESTS_PASS,
        ClaimType.TEST_COUNT,
        ClaimType.BUG_FIXED,
        ClaimType.FEATURE_IMPLEMENTED,
        ClaimType.TASK_COMPLETE,
        ClaimType.BUILD_SUCCEEDS,
    }
)

Extractor = Literal["pattern", "model", "seeded"]


@dataclass(frozen=True)
class Claim:
    """One atomic claim from a final report.

    Attributes:
        claim_id: Stable within one report: ``"c0"``, ``"c1"``, ... in report order.
        type: The claim type.
        text: The sentence or clause the claim came from, verbatim.
        span: ``(start, end)`` character offsets of ``text`` in the report.
        params: Type-specific arguments (see the module docstring).
        negated: True for negative statements ("tests still fail").
        extractor: Which extractor produced it.
    """

    claim_id: str
    type: ClaimType
    text: str
    span: tuple[int, int]
    params: Mapping[str, ParamValue] = field(default_factory=dict)
    negated: bool = False
    extractor: Extractor = "pattern"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable form."""
        return {
            "claim_id": self.claim_id,
            "type": self.type.value,
            "text": self.text,
            "span": list(self.span),
            "params": dict(self.params),
            "negated": self.negated,
            "extractor": self.extractor,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Claim:
        """Inverse of :meth:`to_dict`; raises ValueError on malformed input."""
        try:
            span = data["span"]
            params = data.get("params", {})
            if not isinstance(span, list | tuple) or len(span) != 2:
                raise ValueError("span must be a pair")
            if not isinstance(params, Mapping):
                raise ValueError("params must be an object")
            extractor = str(data.get("extractor", "pattern"))
            if extractor not in ("pattern", "model", "seeded"):
                raise ValueError(f"unknown extractor {extractor!r}")
            return cls(
                claim_id=str(data["claim_id"]),
                type=ClaimType(str(data["type"])),
                text=str(data["text"]),
                span=(int(span[0]), int(span[1])),
                params={str(k): _param(v) for k, v in params.items()},
                negated=bool(data.get("negated", False)),
                extractor=cast(Extractor, extractor),
            )
        except KeyError as exc:
            raise ValueError(f"claim missing {exc}") from exc


def _param(value: object) -> ParamValue:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return value
    return str(value)
