"""Which claims make a report a success report (claims below are synthetic)."""

from __future__ import annotations

from receipts.claims.types import Claim, ClaimType
from receipts.verify.verifier import claims_success


def claim(ctype: ClaimType, negated: bool = False, **params: str | int | None) -> Claim:
    return Claim("c0", ctype, "text", (0, 4), params, negated)


def test_success_claims() -> None:
    assert claims_success(claim(ClaimType.TESTS_PASS))
    assert claims_success(claim(ClaimType.TASK_COMPLETE))
    assert claims_success(claim(ClaimType.TEST_COUNT, passed=42, total=42, failed=0))
    assert claims_success(claim(ClaimType.TEST_COUNT, passed=42, total=42))


def test_admissions_and_other_types_are_not_success() -> None:
    assert not claims_success(claim(ClaimType.TESTS_PASS, negated=True))
    assert not claims_success(claim(ClaimType.TEST_COUNT, passed=39, failed=3))
    assert not claims_success(claim(ClaimType.TEST_COUNT, passed=39, failed="3"))
    assert claims_success(claim(ClaimType.TEST_COUNT, passed=39, failed="none"))
    assert not claims_success(claim(ClaimType.FILE_MODIFIED, path="a.py"))
