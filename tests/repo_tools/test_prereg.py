"""Tests for the preregistration hash chain."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import prereg

Commit = Callable[[Path, str], str]


def setup_prereg(root: Path, commit: Commit) -> None:
    (root / "prereg").mkdir()
    (root / "prereg" / "0001-e1-main.md").write_text("# E1\nplanned_runs_per_config: 60\n")
    prereg.freeze(root, "prereg/0001-e1-main.md", "2026-10-23")
    commit(root, "freeze e1")


def write_artifact(root: Path, rel: str, **extra: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"confirmatory": True, **extra}))


def test_freeze_and_verify_clean(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    digest = prereg.load_lock(git_repo)[0].sha256
    write_artifact(
        git_repo,
        "artifacts/e1/results.json",
        prereg="prereg/0001-e1-main.md",
        prereg_sha256=digest,
    )
    commit(git_repo, "data")
    result = prereg.verify(git_repo)
    assert result.ok, result.problems
    assert result.frozen == 1
    assert result.confirmatory_artifacts == ["artifacts/e1/results.json"]


def test_freeze_rejects_bad_names_and_refreeze(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    with pytest.raises(ValueError, match="already frozen"):
        prereg.freeze(git_repo, "prereg/0001-e1-main.md", "2026-10-23")
    with pytest.raises(ValueError, match="does not match"):
        prereg.freeze(git_repo, "prereg/e1.md", "2026-10-23")


def test_edit_after_freeze_is_caught(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    (git_repo / "prereg" / "0001-e1-main.md").write_text("# E1 edited\n")
    commit(git_repo, "sneaky edit")
    problems = prereg.verify(git_repo).problems
    assert any("changed after it was frozen" in p for p in problems)
    assert any("modified in a commit after its freeze" in p for p in problems)


def test_artifact_in_same_commit_as_freeze_fails(git_repo: Path, commit: Commit) -> None:
    (git_repo / "prereg").mkdir()
    (git_repo / "prereg" / "0001-e1-main.md").write_text("# E1\n")
    entry = prereg.freeze(git_repo, "prereg/0001-e1-main.md", "2026-10-23")
    write_artifact(git_repo, "artifacts/e1/r.json", prereg=entry.file, prereg_sha256=entry.sha256)
    commit(git_repo, "prereg and data together")
    problems = prereg.verify(git_repo).problems
    assert any("does not come after" in p for p in problems)


def test_artifact_problems(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    write_artifact(git_repo, "artifacts/a.json")
    write_artifact(
        git_repo, "artifacts/b.json", prereg="prereg/0001-e1-main.md", prereg_sha256="0" * 64
    )
    (git_repo / "artifacts" / "not_json.json").write_text("{")
    (git_repo / "artifacts" / "exploratory.json").write_text(json.dumps({"confirmatory": False}))
    commit(git_repo, "data")
    digest = prereg.load_lock(git_repo)[0].sha256
    write_artifact(
        git_repo, "artifacts/c.json", prereg="prereg/0001-e1-main.md", prereg_sha256=digest
    )
    problems = prereg.verify(git_repo).problems
    assert any("a.json is confirmatory but cites no frozen prereg" in p for p in problems)
    assert any("b.json prereg_sha256 does not match" in p for p in problems)
    assert any("c.json is not committed" in p for p in problems)


def test_chain_tampering_and_missing_file(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    lock = json.loads((git_repo / prereg.LOCK).read_text())
    lock["entries"][0]["prev"] = "f" * 64
    (git_repo / prereg.LOCK).write_text(json.dumps(lock))
    (git_repo / "prereg" / "0001-e1-main.md").unlink()
    problems = prereg.verify(git_repo).problems
    assert any("hash chain broken" in p for p in problems)
    assert any("frozen but missing" in p for p in problems)


def test_uncommitted_lock_and_unreadable_lock(git_repo: Path, commit: Commit) -> None:
    (git_repo / "prereg").mkdir()
    (git_repo / "prereg" / "0001-x.md").write_text("x\n")
    prereg.freeze(git_repo, "prereg/0001-x.md", "2026-10-23")
    commit(git_repo, "init")
    (git_repo / "prereg" / "0002-y.md").write_text("y\n")
    prereg.freeze(git_repo, "prereg/0002-y.md", "2026-10-23")
    problems = prereg.verify(git_repo).problems
    assert any("lock is not committed" in p for p in problems)
    (git_repo / prereg.LOCK).write_text("{")
    assert any("unreadable" in p for p in prereg.verify(git_repo).problems)


def test_amendments_and_drafts(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    (git_repo / "prereg" / "0002-amend.md").write_text("Amends: prereg/0001-e1-main.md\n")
    (git_repo / "prereg" / "0003-bad.md").write_text("Amends: prereg/0009-none.md\n")
    (git_repo / "prereg" / "Notes.md").write_text("bad name\n")
    (git_repo / "prereg" / "README.md").write_text("ok\n")
    result = prereg.verify(git_repo)
    assert "prereg/0002-amend.md" in result.drafts
    assert any("amends prereg/0009-none.md" in p for p in result.problems)
    assert any("Notes.md does not match" in p for p in result.problems)


def test_main_cli(git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]) -> None:
    (git_repo / "prereg").mkdir()
    (git_repo / "prereg" / "0001-x.md").write_text("x\n")
    commit(git_repo, "init")
    args = ["--root", str(git_repo)]
    assert prereg.main([*args, "freeze", "prereg/0001-x.md", "--date", "2026-10-23"]) == 0
    commit(git_repo, "freeze")
    assert prereg.main([*args, "verify"]) == 0
    assert "PREREG-VERIFY: PASS" in capsys.readouterr().out
    assert prereg.main([*args, "verify", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
