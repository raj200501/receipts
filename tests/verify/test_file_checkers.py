"""Tests for the file_* and dependency_* checkers (synthetic ledgers)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from receipts.claims.types import ClaimType
from receipts.verify import Finding, Label, LedgerFacts, verify_claim
from receipts.verify.checkers import FileView, file_view, normalize_dependency, version_matches
from tests.verify.ledgers import SyntheticLedger, claim

S, C, U = Label.SUPPORTED, Label.CONTRADICTED, Label.UNVERIFIABLE
MOD, NEW, DEL, SAME = (
    ClaimType.FILE_MODIFIED,
    ClaimType.FILE_CREATED,
    ClaimType.FILE_DELETED,
    ClaimType.FILE_UNCHANGED,
)


def _diff(lb: SyntheticLedger) -> int:
    lb.start()
    return lb.diff(
        [
            {"path": "src/app/config.py", "status": "M"},
            {"path": "src/app/new.py", "status": "A"},
            {"path": "src/app/old.py", "status": "D"},
            {"path": "src/app/renamed.py", "status": "R", "old_path": "src/app/legacy.py"},
            {"path": "src/a/util.py", "status": "M"},
            {"path": "src/b/util.py", "status": "M"},
        ]
    )


@pytest.mark.parametrize(
    ("kind", "path", "expected"),
    [
        (MOD, "config.py", S),
        (MOD, "src/app/new.py", S),
        (MOD, "renamed.py", S),
        (MOD, "legacy.py", S),
        (MOD, "old.py", C),
        (MOD, "README.md", C),
        (MOD, "util.py", U),
        (MOD, "src/a/util.py", S),
        (NEW, "new.py", S),
        (NEW, "renamed.py", S),
        (NEW, "config.py", C),
        (NEW, "README.md", C),
        (DEL, "old.py", S),
        (DEL, "legacy.py", S),
        (DEL, "config.py", C),
        (DEL, "never.py", C),
        (SAME, "README.md", S),
        (SAME, "config.py", C),
        (SAME, "legacy.py", C),
        (SAME, "old.py", C),
        (SAME, "util.py", U),
    ],
)
def test_file_claims_against_diff(
    lb: SyntheticLedger, kind: ClaimType, path: str, expected: Label
) -> None:
    diff = _diff(lb)
    verdict = verify_claim(claim(kind, path=path), lb.ledger())
    assert verdict.label is expected, verdict.reason
    assert diff in verdict.evidence


def test_file_modified_reason_names_the_file(lb: SyntheticLedger) -> None:
    diff = _diff(lb)
    verdict = verify_claim(claim(MOD, "updated config.py", path="config.py"), lb.ledger())
    assert verdict.checker == "check_file_modified"
    assert verdict.reason == (
        f"src/app/config.py is modified in the post-run diff (event {diff}),"
        " no agent write touched it"
    )


def test_file_ambiguous_reason(lb: SyntheticLedger) -> None:
    _diff(lb)
    verdict = verify_claim(claim(MOD, path="util.py"), lb.ledger())
    assert "matches several changed files (src/a/util.py, src/b/util.py)" in verdict.reason


def test_file_modified_by_agent_write_without_diff(lb: SyntheticLedger) -> None:
    lb.start()
    seq = lb.write("src/app.py")
    verdict = verify_claim(claim(MOD, path="app.py"), lb.ledger())
    assert verdict.label is S
    assert verdict.evidence == (seq,)
    assert f"modify (event {seq})" in verdict.reason


def test_file_modified_without_diff_and_other_writes_is_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("src/app.py")
    verdict = verify_claim(claim(MOD, path="src/other.py"), lb.ledger())
    assert verdict.label is U
    assert "no post-run diff" in verdict.reason


def test_file_claims_without_diff_or_writes_are_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    for kind in (MOD, NEW, DEL, SAME):
        verdict = verify_claim(claim(kind, path="a.py"), lb.ledger())
        assert verdict.label is U
        assert "no post-run diff and no agent file write" in verdict.reason


def test_file_claims_without_path(lb: SyntheticLedger) -> None:
    _diff(lb)
    verdict = verify_claim(claim(MOD), lb.ledger())
    assert verdict.label is U
    assert verdict.reason == "the claim names no file"


def test_file_created_by_write_op_create(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("tests/test_new.py", op="create")
    assert verify_claim(claim(NEW, path="test_new.py"), lb.ledger()).label is S


def test_file_created_with_modify_write_and_no_diff_is_unverifiable(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py", op="modify")
    assert verify_claim(claim(NEW, path="a.py"), lb.ledger()).label is U


def test_file_deleted_by_write_op_delete(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("old.py", op="delete")
    assert verify_claim(claim(DEL, path="old.py"), lb.ledger()).label is S


def test_file_unchanged_contradicted_by_write_then_revert(lb: SyntheticLedger) -> None:
    lb.start()
    first = lb.write("settings.py")
    second = lb.write("settings.py")
    diff = lb.diff([])
    verdict = verify_claim(
        claim(SAME, "did not touch settings.py", path="settings.py"), lb.ledger()
    )
    assert verdict.label is C
    assert verdict.evidence == (first, second, diff)
    assert "is not in the post-run diff" in verdict.reason


def test_file_unchanged_without_diff(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("a.py")
    ledger = lb.ledger()
    assert verify_claim(claim(SAME, path="b.py"), ledger).label is U
    verdict = verify_claim(claim(SAME, path="a.py"), ledger)
    assert verdict.label is C
    assert "has no diff" in verdict.reason


def test_file_negated_modified(lb: SyntheticLedger) -> None:
    _diff(lb)
    c = claim(MOD, "I did not change config.py", negated=True, path="config.py")
    assert verify_claim(c, lb.ledger()).label is C


def test_file_view_statuses(lb: SyntheticLedger) -> None:
    _diff(lb)
    facts = LedgerFacts(lb.ledger())
    view = file_view(claim(MOD, path="legacy.py"), facts)
    assert isinstance(view, FileView)
    assert view.path == "src/app/legacy.py"
    assert view.status == "R-old"
    assert view.ops() == set()
    missing = file_view(claim(MOD, path="nope.py"), facts)
    assert isinstance(missing, FileView)
    assert missing.path is None
    assert missing.status is None
    assert isinstance(file_view(claim(MOD), facts), Finding)


def test_file_view_unknown_status_in_reason(lb: SyntheticLedger) -> None:
    lb.start()
    lb.raw("diff", {"files": [{"path": "x.py", "status": "T"}], "source": "snapshot"})
    verdict = verify_claim(claim(SAME, path="x.py"), lb.ledger())
    assert verdict.label is C
    assert "status T" in verdict.reason


# --- dependencies ----------------------------------------------------------------------


def _deps(lb: SyntheticLedger) -> int:
    lb.start()
    return lb.diff(
        [{"path": "pyproject.toml", "status": "M"}],
        [
            {
                "manifest": "pyproject.toml",
                "name": "httpx",
                "change": "added",
                "old": None,
                "new": ">=0.27",
            },
            {
                "manifest": "pyproject.toml",
                "name": "Flask_Login",
                "change": "changed",
                "old": "==0.6.2",
                "new": "==0.6.3",
            },
            {
                "manifest": "package.json",
                "name": "@types/node",
                "change": "changed",
                "old": "^18.0.0",
                "new": "^20.11.0",
            },
            {
                "manifest": "requirements.txt",
                "name": "six",
                "change": "removed",
                "old": "1.16",
                "new": None,
            },
            {
                "manifest": "pyproject.toml",
                "name": "attrs",
                "change": "added",
                "old": None,
                "new": None,
            },
        ],
    )


@pytest.mark.parametrize(
    ("kind", "params", "expected"),
    [
        (ClaimType.DEPENDENCY_ADDED, {"name": "httpx"}, S),
        (ClaimType.DEPENDENCY_ADDED, {"name": "HTTPX", "version": "0.27"}, S),
        (ClaimType.DEPENDENCY_ADDED, {"name": "httpx", "version": "0.28"}, C),
        (ClaimType.DEPENDENCY_ADDED, {"name": "attrs", "version": "23.1"}, S),
        (ClaimType.DEPENDENCY_ADDED, {"name": "flask-login"}, C),
        (ClaimType.DEPENDENCY_ADDED, {"name": "requests"}, C),
        (ClaimType.DEPENDENCY_UPDATED, {"name": "flask-login", "version": "0.6.3"}, S),
        (ClaimType.DEPENDENCY_UPDATED, {"name": "flask_login>=0.6"}, S),
        (ClaimType.DEPENDENCY_UPDATED, {"name": "@types/node", "version": "20"}, S),
        (ClaimType.DEPENDENCY_UPDATED, {"name": "@types/node@21"}, S),
        (ClaimType.DEPENDENCY_UPDATED, {"name": "@types/node", "version": "21"}, C),
        (ClaimType.DEPENDENCY_UPDATED, {"name": "httpx"}, C),
        (ClaimType.DEPENDENCY_REMOVED, {"name": "six", "version": "9"}, S),
        (ClaimType.DEPENDENCY_REMOVED, {"name": "httpx"}, C),
    ],
)
def test_dependency_claims(
    lb: SyntheticLedger, kind: ClaimType, params: dict[str, str], expected: Label
) -> None:
    diff = _deps(lb)
    verdict = verify_claim(replace(claim(kind), params=params), lb.ledger())
    assert verdict.label is expected, verdict.reason
    assert verdict.evidence == (diff,)


def test_dependency_reasons(lb: SyntheticLedger) -> None:
    diff = _deps(lb)
    ledger = lb.ledger()
    added = verify_claim(claim(ClaimType.DEPENDENCY_ADDED, name="httpx"), ledger)
    assert added.reason == (
        f"the post-run diff (event {diff}) shows httpx added in pyproject.toml (none to >=0.27)"
    )
    assert added.checker == "check_dependency_added"
    wrong_kind = verify_claim(claim(ClaimType.DEPENDENCY_REMOVED, name="httpx"), ledger)
    assert "shows httpx added in pyproject.toml, not removed" in wrong_kind.reason
    missing = verify_claim(claim(ClaimType.DEPENDENCY_ADDED, name="requests"), ledger)
    assert "has no dependency change for requests" in missing.reason
    version = verify_claim(claim(ClaimType.DEPENDENCY_ADDED, name="httpx", version="1.0"), ledger)
    assert "not version 1.0" in version.reason


def test_dependency_unverifiable_without_diff(lb: SyntheticLedger) -> None:
    lb.start()
    lb.write("pyproject.toml")
    verdict = verify_claim(claim(ClaimType.DEPENDENCY_ADDED, name="httpx"), lb.ledger())
    assert verdict.label is U
    assert "no post-run diff" in verdict.reason


def test_dependency_without_name(lb: SyntheticLedger) -> None:
    _deps(lb)
    verdict = verify_claim(claim(ClaimType.DEPENDENCY_REMOVED), lb.ledger())
    assert verdict.label is U


def test_dependency_negated(lb: SyntheticLedger) -> None:
    _deps(lb)
    c = claim(ClaimType.DEPENDENCY_ADDED, "no new dependencies", negated=True, name="requests")
    assert verify_claim(c, lb.ledger()).label is S


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Flask_Login", "flask-login"),
        ("requests>=2.31", "requests"),
        ("uvicorn[standard]", "uvicorn"),
        ("@types/node@20", "@types/node"),
        ("'lodash'", "lodash"),
        ("", ""),
    ],
)
def test_normalize_dependency(raw: str, expected: str) -> None:
    assert normalize_dependency(raw) == expected


@pytest.mark.parametrize(
    ("claimed", "spec", "expected"),
    [
        ("2.32", "^2.32.3", True),
        ("2.32.3", ">=2.32", True),
        ("v2", "2.0.1", True),
        ("2.3", "2.32.3", False),
        ("latest", "1.0", True),
        ("1.0", None, True),
        ("3", ">=1,<3", True),
        ("4", ">=1,<3", False),
    ],
)
def test_version_matches(claimed: str, spec: str | None, expected: bool) -> None:
    assert version_matches(claimed, spec) is expected
