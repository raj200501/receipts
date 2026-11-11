"""Derived artifacts and their re-derivation (``receipts.report.derived``, gate G10).

The run records here are synthetic test fixtures, never model output. The summary
script is the real ``tools/smoke_outcomes.py``, copied into a temporary repository, so
the checks run the same derivation as ``make freshness`` does on the real artifacts.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import freshness
import report
from receipts.report.derived import (
    DERIVED,
    Derived,
    DerivedError,
    check,
    comparable,
    refresh,
)
from tests.repo_tools.test_smoke_outcomes import record

ROOT = Path(__file__).resolve().parents[2]
SMOKE = DERIVED[0]
RUNS = "artifacts/studies/smoke/runs"
Commit = Callable[[Path, str], str]


def bank_run(root: Path, rec: dict[str, Any]) -> str:
    """Write one synthetic run record where the smoke study banks it; returns its path."""
    rel = f"{RUNS}/{rec['run_id']}/run.json"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec), encoding="utf-8")
    return rel


def repo(root: Path, commit: Commit) -> Path:
    """A repository holding the real summary script and two banked synthetic runs."""
    (root / "tools").mkdir()
    shutil.copy(ROOT / "tools" / "smoke_outcomes.py", root / "tools" / "smoke_outcomes.py")
    bank_run(root, record("smoke-py-a", success_reported=True, done=False))
    bank_run(root, record("smoke-ts-b", success_reported=False, done=False))
    commit(root, "start")
    return root


def test_the_smoke_summary_is_registered_with_its_script_and_inputs() -> None:
    assert (SMOKE.path, SMOKE.script, SMOKE.inputs) == (
        "artifacts/exploratory/smoke_outcomes.json",
        "tools/smoke_outcomes.py",
        f"{RUNS}/*/run.json",
    )
    assert isinstance(SMOKE, Derived)
    volatile = {"git_sha": "a", "created": "t", "command": "c", "environment": {"python": "3"}}
    art = {"summary": 1, "provenance": {**volatile, "x": 2}}
    assert comparable(art) == {"summary": 1, "provenance": {"x": 2}}


def test_refresh_writes_a_missing_summary_once_and_then_leaves_it(
    git_repo: Path, commit: Commit
) -> None:
    root = repo(git_repo, commit)
    (missing,) = check(root)
    assert missing.startswith(f"{SMOKE.path}: missing, though") and "make report" in missing
    assert refresh(root) == [SMOKE.path]
    assert check(root) == []
    before = (root / SMOKE.path).read_bytes()
    assert refresh(root) == []  # nothing changed, so no rewrite and no new timestamp
    assert (root / SMOKE.path).read_bytes() == before


def test_a_run_banked_after_the_summary_makes_it_stale(git_repo: Path, commit: Commit) -> None:
    root = repo(git_repo, commit)
    refresh(root)
    new = bank_run(root, record("smoke-py-c", success_reported=True, done=False))

    inputs, content = check(root)
    assert f"new: {new}" in inputs and "recorded inputs are not the current" in inputs
    assert content.startswith(f"{SMOKE.path}: differs from a fresh derivation")
    assert "runs" in content and "summary" in content and "provenance.inputs" in content
    assert refresh(root) == [SMOKE.path]
    assert check(root) == []
    summary = json.loads((root / SMOKE.path).read_text(encoding="utf-8"))["summary"]
    assert summary["runs"] == 3


def test_a_summary_value_typed_by_hand_fails_although_the_inputs_are_current(
    git_repo: Path, commit: Commit
) -> None:
    root = repo(git_repo, commit)
    refresh(root)
    path = root / SMOKE.path
    art = json.loads(path.read_text(encoding="utf-8"))
    art["summary"]["false_success"]["k"] = 0
    path.write_text(json.dumps(art, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert check(root) == [
        f"{SMOKE.path}: differs from a fresh derivation by {SMOKE.script} (summary); "
        "run make report"
    ]


def test_changed_and_removed_inputs_are_named(git_repo: Path, commit: Commit) -> None:
    root = repo(git_repo, commit)
    refresh(root)
    changed = root / RUNS / "smoke-py-a" / "run.json"
    rec = json.loads(changed.read_text(encoding="utf-8"))
    rec["turns"] = 9
    changed.write_text(json.dumps(rec), encoding="utf-8")
    shutil.rmtree(root / RUNS / "smoke-ts-b")

    inputs = check(root)[0]
    assert f"changed: {RUNS}/smoke-py-a/run.json" in inputs
    assert f"removed: {RUNS}/smoke-ts-b/run.json" in inputs


def test_missing_scripts_bad_artifacts_and_failing_derivations(tmp_path: Path) -> None:
    assert check(tmp_path) == [] and refresh(tmp_path) == []  # nothing banked, nothing derived
    target = tmp_path / SMOKE.path
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    assert check(tmp_path)[0].startswith(f"{SMOKE.path}: not JSON")
    target.write_text("[]", encoding="utf-8")
    assert check(tmp_path) == [f"{SMOKE.path}: not a JSON object"]
    target.write_text('{"provenance": {"inputs": {}}}', encoding="utf-8")
    assert check(tmp_path) == [f"{SMOKE.path}: {SMOKE.script} is missing"]
    marked = record("smoke-py-x", success_reported=True, done=False)
    marked["synthetic"] = True  # the script refuses synthetic records
    bank_run(tmp_path, marked)
    (tmp_path / "tools").mkdir()
    shutil.copy(ROOT / "tools" / "smoke_outcomes.py", tmp_path / "tools" / "smoke_outcomes.py")
    with pytest.raises(DerivedError, match="failed: a run record is marked synthetic"):
        refresh(tmp_path)


def test_make_report_freshness_and_reproduce_follow_the_banked_runs(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(git_repo, commit)
    assert report.main(["--root", str(root)]) == 0  # make report: re-derives, then builds
    assert f"re-derived {SMOKE.path}" in capsys.readouterr().out
    assert report.main(["--root", str(root), "--reproduce"]) == 0
    registry = (root / "artifacts" / "report" / "numbers.json").read_text(encoding="utf-8")
    stub = (
        "import sys, pathlib\n"
        f"pathlib.Path(sys.argv[sys.argv.index('--out') + 1]).write_text({registry!r})\n"
    )
    (root / "tools" / "report.py").write_text(stub, encoding="utf-8")
    (root / "README.md").write_text("<!--n:smoke.runs-->2<!--/n-->\n", encoding="utf-8")
    assert freshness.main(["--root", str(root), "README.md"]) == 0
    capsys.readouterr()

    bank_run(root, record("smoke-py-c", success_reported=True, done=False))
    assert freshness.main(["--root", str(root), "README.md"]) == 1
    assert "differs from a fresh derivation" in capsys.readouterr().out
    assert report.main(["--root", str(root), "--reproduce"]) == 1
    assert "recorded inputs are not the current" in capsys.readouterr().out
