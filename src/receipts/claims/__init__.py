"""Atomic claims extracted from an agent's final report.

:func:`extract_claims` is the entry point: deterministic pattern rules for the common
claim types, plus an optional model extractor for units no pattern covers.
"""

from receipts.claims.extract import extract_claims
from receipts.claims.model import (
    CLAIM_JSON_SCHEMA,
    ModelExtractor,
    build_prompt,
    parse_response,
)
from receipts.claims.patterns import pattern_claims
from receipts.claims.segment import Segmentation, Unit, segment
from receipts.claims.types import SUCCESS_TYPES, Claim, ClaimType

__all__ = [
    "CLAIM_JSON_SCHEMA",
    "SUCCESS_TYPES",
    "Claim",
    "ClaimType",
    "ModelExtractor",
    "Segmentation",
    "Unit",
    "build_prompt",
    "extract_claims",
    "parse_response",
    "pattern_claims",
    "segment",
]
