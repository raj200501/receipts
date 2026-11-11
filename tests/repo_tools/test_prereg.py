"""Tests for the preregistration hash chain."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
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


# ---------------------------------------------------------------- unfinished drafts (D42 item 6)
# The texts below are SYNTHETIC preregistrations written only for these tests.

DRAFT_STATUS = (
    "Status: DRAFT. Not frozen. Fields marked TO FIX BEFORE FREEZE are filled before the\nfreeze.\n"
)
FILLED = "# E9 (SYNTHETIC)\n\nStatus: FROZEN on 2026-11-05.\n\nplanned_runs_per_config: 64\n"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(f"# E9 (SYNTHETIC)\n\n{DRAFT_STATUS}", id="the-draft-status-paragraph"),
        pytest.param(FILLED + "- K: TO FIX BEFORE FREEZE\n", id="a-placeholder"),
        pytest.param(FILLED + "K is fixed later (TO FIX BEFORE\nFREEZE).\n", id="a-wrapped-one"),
        pytest.param(FILLED + "- K: to fix before freeze\n", id="in-lower-case"),
        pytest.param("# E9 (SYNTHETIC)\n\nStatus: DRAFT\n", id="a-draft-status-line"),
        pytest.param("# E9 (SYNTHETIC)\n\n**Status:** Draft, not frozen\n", id="emphasized"),
        pytest.param("# E9 (SYNTHETIC)\n\n> status:draft\n", id="quoted-without-a-space"),
    ],
)
def test_freeze_refuses_an_unfinished_draft(git_repo: Path, text: str) -> None:
    (git_repo / "prereg").mkdir()
    (git_repo / "prereg" / "0009-e9.md").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=r"TO FIX BEFORE FREEZE|Status: DRAFT"):
        prereg.freeze(git_repo, "prereg/0009-e9.md", "2026-11-05")
    assert not (git_repo / prereg.LOCK).exists()


def test_freeze_accepts_a_filled_file_that_names_the_rules(git_repo: Path) -> None:
    # Words near the markers are not the markers: a status other than DRAFT, a draft
    # mentioned later in a line, and the freeze rule paraphrased without the phrase.
    text = (
        FILLED + "The Status line said DRAFT until the freeze commit.\n"
        "Status: FROZEN (it was a DRAFT before).\n"
        "Placeholders to fix were filled before the freeze.\n"
    )
    (git_repo / "prereg").mkdir()
    (git_repo / "prereg" / "0009-e9.md").write_text(text, encoding="utf-8")
    entry = prereg.freeze(git_repo, "prereg/0009-e9.md", "2026-11-05")
    assert entry.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert [e.file for e in prereg.load_lock(git_repo)] == ["prereg/0009-e9.md"]


def test_freeze_refuses_a_missing_or_non_text_file(git_repo: Path) -> None:
    (git_repo / "prereg").mkdir()
    with pytest.raises(ValueError, match="does not exist"):
        prereg.freeze(git_repo, "prereg/0009-e9.md", "2026-11-05")
    (git_repo / "prereg" / "0009-e9.md").write_bytes(b"# E9 \xff\xfe SYNTHETIC\n")
    with pytest.raises(ValueError, match="not UTF-8 text"):
        prereg.freeze(git_repo, "prereg/0009-e9.md", "2026-11-05")
    assert not (git_repo / prereg.LOCK).exists()


def test_main_reports_a_refused_freeze(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (git_repo / "prereg").mkdir()
    (git_repo / "prereg" / "0009-e9.md").write_text(f"# E9\n\n{DRAFT_STATUS}", "utf-8")
    args = ["--root", str(git_repo), "freeze", "prereg/0009-e9.md", "--date", "2026-11-05"]
    assert prereg.main(args) == 2
    err = capsys.readouterr().err
    assert err.startswith("prereg freeze: refused: prereg/0009-e9.md")
    assert "TO FIX BEFORE FREEZE" in err and "Traceback" not in err
    assert not (git_repo / prereg.LOCK).exists()


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


# ---------------------------------------------------------------- lock history (H31)
# Every repository below is a small synthetic git repository built under tmp_path.


def test_dropped_lock_entry_is_caught(git_repo: Path, commit: Commit) -> None:
    """A frozen prereg withdrawn from LOCK.json and replaced by a later one (synthetic)."""
    setup_prereg(git_repo, commit)
    (git_repo / "prereg" / "0001-e1-main.md").unlink()
    prereg.write_lock(git_repo, [])
    (git_repo / "prereg" / "0003-e1-main-v2.md").write_text("# E1 rewritten after the data\n")
    entry = prereg.freeze(git_repo, "prereg/0003-e1-main-v2.md", "2026-10-24")
    commit(git_repo, "withdraw 0001, freeze 0003")
    write_artifact(
        git_repo, "artifacts/e1/results.json", prereg=entry.file, prereg_sha256=entry.sha256
    )
    commit(git_repo, "data")
    problems = prereg.verify(git_repo).problems
    assert any("drops or rewrites frozen entries: prereg/0001-e1-main.md" in p for p in problems), (
        problems
    )


def test_reordered_lock_with_valid_hashes_is_caught(git_repo: Path, commit: Commit) -> None:
    """The chain rebuilt in another order keeps valid hashes but rewrites history (synthetic)."""
    setup_prereg(git_repo, commit)
    (git_repo / "prereg" / "0002-e4.md").write_text("# E4\n")
    prereg.freeze(git_repo, "prereg/0002-e4.md", "2026-10-24")
    commit(git_repo, "freeze e4")
    rebuilt: list[prereg.LockEntry] = []
    prev = prereg.GENESIS
    for old in reversed(prereg.load_lock(git_repo)):
        digest = prereg.entry_hash(prev, old.file, old.sha256)
        rebuilt.append(prereg.LockEntry(old.file, old.sha256, prev, digest, old.frozen_at))
        prev = digest
    prereg.write_lock(git_repo, rebuilt)
    commit(git_repo, "reorder the chain")
    problems = prereg.verify(git_repo).problems
    assert any("drops or rewrites frozen entries" in p for p in problems), problems


def test_rewritten_entry_and_deleted_lock_are_caught(git_repo: Path, commit: Commit) -> None:
    """An entry's freeze date rewritten, then LOCK.json deleted and restored (synthetic)."""
    setup_prereg(git_repo, commit)
    [entry] = prereg.load_lock(git_repo)
    prereg.write_lock(git_repo, [dataclasses.replace(entry, frozen_at="2026-01-01")])
    commit(git_repo, "backdate")
    problems = prereg.verify(git_repo).problems
    assert any("drops or rewrites frozen entries: prereg/0001-e1-main.md" in p for p in problems)
    prereg.write_lock(git_repo, [entry])
    commit(git_repo, "restore the date")
    lock_text = (git_repo / prereg.LOCK).read_text()
    (git_repo / prereg.LOCK).unlink()
    commit(git_repo, "delete the lock")
    (git_repo / prereg.LOCK).write_text(lock_text)
    commit(git_repo, "restore the lock")
    problems = prereg.verify(git_repo).problems
    assert sum("drops or rewrites frozen entries" in p for p in problems) == 3, problems


def test_working_tree_lock_must_extend_the_committed_one(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    prereg.write_lock(git_repo, [])
    problems = prereg.verify(git_repo).problems
    assert any("working tree drops or rewrites" in p for p in problems), problems


def test_unreadable_historical_lock_is_a_problem(git_repo: Path, commit: Commit) -> None:
    """A malformed committed LOCK.json is reported, never a crash and never skipped."""
    (git_repo / "prereg").mkdir()
    (git_repo / prereg.LOCK).write_text("{")
    (git_repo / "prereg" / "0001-x.md").write_text("x\n")
    commit(git_repo, "broken lock")
    (git_repo / prereg.LOCK).unlink()
    prereg.freeze(git_repo, "prereg/0001-x.md", "2026-10-23")
    commit(git_repo, "freeze")
    problems = prereg.verify(git_repo).problems
    assert any("is unreadable" in p and "at commit" in p for p in problems), problems


def test_shallow_clone_is_refused(git_repo: Path, commit: Commit, tmp_path: Path) -> None:
    """A shallow clone hides the history, so verify must not pass on it (synthetic)."""
    setup_prereg(git_repo, commit)
    (git_repo / "notes.txt").write_text("later work\n")
    commit(git_repo, "later")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{git_repo}", str(shallow)], check=True
    )
    problems = prereg.verify(shallow).problems
    assert any("shallow clone" in p for p in problems), problems


# ---------------------------------------------------------------- raw confirmatory data (H32)


def cite_e1(root: Path) -> None:
    digest = prereg.load_lock(root)[0].sha256
    write_artifact(
        root, "artifacts/e1/results.json", prereg="prereg/0001-e1-main.md", prereg_sha256=digest
    )


def write_file(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


ROWS = "".join(f'{{"run_id": "r{i}", "false_success": {i % 2}}}\n' for i in range(40))


def test_runs_jsonl_banked_before_freeze_fails(git_repo: Path, commit: Commit) -> None:
    """Raw E1 rows committed before the freeze, results after it (synthetic)."""
    write_file(git_repo, "artifacts/e1/runs.jsonl", ROWS)
    commit(git_repo, "data first")
    setup_prereg(git_repo, commit)
    cite_e1(git_repo)
    commit(git_repo, "results")
    problems = prereg.verify(git_repo).problems
    assert any(
        "artifacts/e1/runs.jsonl" in p and "at or before prereg/0001-e1-main.md was frozen" in p
        for p in problems
    ), problems


def test_run_directory_banked_before_freeze_fails(git_repo: Path, commit: Commit) -> None:
    write_file(git_repo, "artifacts/studies/e1/runs/r1/run.json", '{"run_id": "r1"}\n')
    commit(git_repo, "a run first")
    setup_prereg(git_repo, commit)
    cite_e1(git_repo)
    commit(git_repo, "results")
    problems = prereg.verify(git_repo).problems
    assert any("artifacts/studies/e1/runs/r1/run.json" in p for p in problems), problems


def test_raw_data_renamed_in_after_freeze_fails(git_repo: Path, commit: Commit) -> None:
    """Data committed under another path before the freeze and moved in after (synthetic)."""
    write_file(git_repo, "artifacts/scratch/rows.jsonl", ROWS)
    commit(git_repo, "data under another name")
    setup_prereg(git_repo, commit)
    (git_repo / "artifacts" / "e1").mkdir(parents=True)
    (git_repo / "artifacts" / "scratch" / "rows.jsonl").rename(
        git_repo / "artifacts" / "e1" / "runs.jsonl"
    )
    cite_e1(git_repo)
    commit(git_repo, "move the data in, add results")
    problems = prereg.verify(git_repo).problems
    assert any("artifacts/e1/runs.jsonl" in p and "at or before" in p for p in problems), problems


def test_raw_data_after_freeze_passes_and_is_scoped(git_repo: Path, commit: Commit) -> None:
    """Pilot runs, other experiments, and the plan may predate the freeze (synthetic)."""
    write_file(git_repo, "artifacts/studies/pilot/runs/p1/run.json", '{"run_id": "p1"}\n')
    write_file(git_repo, "artifacts/e3/judges.json", '{"confirmatory": false}\n')
    commit(git_repo, "pilot and an exploratory artifact")
    write_file(git_repo, "artifacts/studies/e1/plan.json", '{"runs": []}\n')
    setup_prereg(git_repo, commit)
    write_file(git_repo, "artifacts/e1/rows-v1.jsonl", ROWS)
    write_file(git_repo, "artifacts/studies/e1/runs/r1/run.json", '{"run_id": "r1"}\n')
    commit(git_repo, "data after the freeze")
    (git_repo / "artifacts" / "e1" / "rows-v1.jsonl").rename(
        git_repo / "artifacts" / "e1" / "runs.jsonl"
    )
    cite_e1(git_repo)
    commit(git_repo, "rename inside the experiment, add results")
    result = prereg.verify(git_repo)
    assert result.ok, result.problems
    assert result.confirmatory_data == [
        "artifacts/e1/runs.jsonl",
        "artifacts/studies/e1/runs/r1/run.json",
    ]


def test_uncommitted_raw_data_is_reported(git_repo: Path, commit: Commit) -> None:
    setup_prereg(git_repo, commit)
    cite_e1(git_repo)
    (git_repo / ".gitignore").write_text("ignored/\n")
    commit(git_repo, "results")
    write_file(git_repo, "artifacts/e1/runs.jsonl", ROWS)
    write_file(git_repo, "artifacts/e1/ignored/cache.json", "{}\n")
    problems = prereg.verify(git_repo).problems
    assert problems == [
        "1 confirmatory data file(s) of e1 are not committed, so their timing cannot be "
        "verified: artifacts/e1/runs.jsonl"
    ]
