"""Evaluation of the receipts instrument itself (E0) and of judges (E3).

The claim-type names live here as plain strings so that the tools blind E0 writers and
adjudicators run (``tools/e0.py check-raw`` and ``check-adjudication``) never import
``receipts.claims`` or ``receipts.verify``. A test checks that :data:`CLAIM_TYPE_NAMES`
equals the values of ``receipts.claims.types.ClaimType``.
"""

#: Every claim type name receipts knows, in ``ClaimType`` order.
CLAIM_TYPE_NAMES: tuple[str, ...] = (
    "tests_pass",
    "test_count",
    "tests_added",
    "ran_command",
    "file_modified",
    "file_created",
    "file_deleted",
    "file_unchanged",
    "dependency_added",
    "dependency_updated",
    "dependency_removed",
    "bug_fixed",
    "feature_implemented",
    "lint_clean",
    "typecheck_clean",
    "build_succeeds",
    "could_not",
    "task_complete",
    "other",
)

#: The types a seeded gold claim may have: the rows of docs/CLAIM_TYPES.md, which is every
#: name except ``other`` (a catch-all with no meaning a fact sheet could settle).
GOLD_CLAIM_TYPES: tuple[str, ...] = tuple(name for name in CLAIM_TYPE_NAMES if name != "other")

__all__ = ["CLAIM_TYPE_NAMES", "GOLD_CLAIM_TYPES"]
