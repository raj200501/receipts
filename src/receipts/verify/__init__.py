"""Check each claim against the ledger: supported, contradicted, or unverifiable."""

from receipts.verify.types import Label, Omission, RunVerification, Verdict

__all__ = ["Label", "Omission", "RunVerification", "Verdict"]
