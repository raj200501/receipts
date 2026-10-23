"""Tests for secrets_scan, budget_report, review, and ship_check helpers."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

import budget_report
import gitutil
import review
import secrets_scan
import ship_check

Commit = Callable[[Path, str], str]
ROOT = Path(__file__).resolve().parents[2]

# Built at runtime so this file never contains a secret-shaped literal.
FAKE_GH = "gh" + "p_" + "A1b2C3d4" * 5
FAKE_AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


def test_scan_text_rules_and_env_values() -> None:
    text = f"token = {FAKE_GH}\nkey {FAKE_AWS}\nvalue my-long-env-secret-value-123\n"
    env = secrets_scan.env_secret_values(
        {"MY_TOKEN": "my-long-env-secret-value-123", "PATH": "x" * 40, "SHORT_KEY": "abc"}
    )
    assert set(env) == {"MY_TOKEN"}
    findings = secrets_scan.scan_text("f.txt", text, env)
    rendered = [str(f) for f in findings]
    assert rendered == [
        "f.txt:1: github-token",
        "f.txt:2: aws-access-key-id",
        "f.txt:3: value of $MY_TOKEN",
    ]
    assert all(FAKE_GH not in r for r in rendered)


def test_scan_files_skips_binary_and_missing(git_repo: Path, commit: Commit) -> None:
    (git_repo / "a.txt").write_text(f"{FAKE_AWS}\n")
    (git_repo / "b.bin").write_bytes(b"\0" + FAKE_AWS.encode())
    commit(git_repo, "files")
    findings, scanned = secrets_scan.scan_files(git_repo, ["a.txt", "b.bin", "gone.txt"], {})
    assert scanned == 1 and [f.rule for f in findings] == ["aws-access-key-id"]


def test_secrets_scan_main(
    git_repo: Path,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(secrets_scan.os, "environ", {})
    (git_repo / "ok.txt").write_text("nothing here\n")
    commit(git_repo, "ok")
    assert secrets_scan.main(["--root", str(git_repo)]) == 0
    (git_repo / "bad.txt").write_text(f"{FAKE_GH}\n")
    commit(git_repo, "bad")
    assert secrets_scan.main(["--root", str(git_repo)]) == 1
    assert "SECRETS-SCAN: FAIL" in capsys.readouterr().out


def copy_budget_inputs(root: Path) -> None:
    (root / "docs").mkdir(exist_ok=True)
    shutil.copy(ROOT / "docs" / "BUILD_BRIEF.md", root / "docs" / "BUILD_BRIEF.md")
    shutil.copy(ROOT / "budget.toml", root / "budget.toml")


def test_budget_report(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copy_budget_inputs(git_repo)
    assert budget_report.main(["--root", str(git_repo)]) == 0
    out = capsys.readouterr().out
    assert "cash_usd = 0\n" in out and "BUDGET: OK" in out
    ledger = git_repo / "artifacts" / "usage" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    row = {"day": "2026-10-23", "backend": "claude", "kind": "review_run"}
    ledger.write_text("\n".join(json.dumps(row) for _ in range(7)) + "\n")
    assert budget_report.main(["--root", str(git_repo)]) == 1
    assert "exceed claude_review_runs_per_day" in capsys.readouterr().out
    (git_repo / "budget.toml").write_text("cash_usd = 1\n")
    assert budget_report.main(["--root", str(git_repo)]) == 1


def review_doc(sha: str, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": "receipts.review/1",
        "reviewed_commit": sha,
        "blocking": [],
        "nonblocking": [{"id": "N1", "title": "t", "evidence": "e"}],
        "text": "Looks fine.\nREVIEW: SHIP",
        "verdict": "SHIP",
    }
    return {**base, **over}


def write_review(root: Path, data: dict[str, object]) -> None:
    path = root / review.LATEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_review_validate(git_repo: Path, commit: Commit) -> None:
    (git_repo / "docs").mkdir()
    (git_repo / "docs" / "REVIEW_LOG.md").write_text("- N1: noted\n")
    (git_repo / "code.py").write_text("x = 1\n")
    sha = commit(git_repo, "code")
    (git_repo / "STATUS.md").write_text("status\n")
    write_review(git_repo, review_doc(sha))
    commit(git_repo, "review + status")
    assert review.validate(git_repo, review_doc(sha)) == []
    (git_repo / "code.py").write_text("x = 2\n")
    commit(git_repo, "code change")
    assert any("code changed" in p for p in review.validate(git_repo, review_doc(sha)))
    bad = review_doc(
        "nothex",
        verdict="SHIP",
        blocking=[{"id": "B1"}],
        text="x\nREVIEW: BLOCK",
        nonblocking=[{"id": "N9"}],
        schema="old",
    )
    problems = review.validate(git_repo, bad)
    assert len(problems) == 5
    assert review.validate(git_repo, review_doc("f" * 40))[0].startswith("reviewed_commit ffff")
    assert "lists" in review.validate(git_repo, review_doc(sha, blocking="x"))[-1]
    assert any(
        "SHIP or BLOCK" in p for p in review.validate(git_repo, review_doc(sha, verdict="?"))
    )


def test_review_main(
    git_repo: Path,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "x")
    args = ["--root", str(git_repo)]
    sha = commit(git_repo, "init")
    assert review.main(args) == 1
    out = capsys.readouterr().out
    assert "billing guard tripped" in out and out.rstrip().endswith("REVIEW: BLOCK")
    (git_repo / "docs").mkdir()
    (git_repo / "docs" / "REVIEW_LOG.md").write_text("N1\n")
    write_review(git_repo, review_doc(sha))
    assert review.main([*args, "--validate-only"]) == 0
    assert capsys.readouterr().out.rstrip().endswith("REVIEW: SHIP")
    write_review(
        git_repo,
        review_doc(sha, verdict="BLOCK", text="1. bad\nREVIEW: BLOCK", blocking=[{"id": "B1"}]),
    )
    assert review.main([*args, "--validate-only"]) == 1
    (git_repo / review.LATEST).write_text("{")
    assert review.main([*args, "--validate-only"]) == 1
    monkeypatch.delenv("ANTHROPIC_BASE_URL")
    monkeypatch.setattr(review.guard, "billing_guard_problems", lambda repo: [])
    assert review.headless_available(git_repo)[0] is False


def test_drift_allowed() -> None:
    assert review.drift_allowed("artifacts/review/latest.json")
    assert review.drift_allowed("STATUS.md") and review.drift_allowed("docs/LOG.md")
    assert not review.drift_allowed("src/receipts/x.py")
    assert not review.drift_allowed("docs/LOG.md.bak")


def test_gitutil_helpers(git_repo: Path, commit: Commit) -> None:
    (git_repo / "a.txt").write_text("a\n")
    first = commit(git_repo, "a")
    (git_repo / "a.txt").write_text("b\n")
    second = commit(git_repo, "b")
    assert gitutil.repo_root(git_repo) == git_repo.resolve()
    assert gitutil.tracked_files(git_repo) == ["a.txt"]
    assert gitutil.first_commit(git_repo, "a.txt") == first
    assert gitutil.first_commit(git_repo, "none.txt") is None
    assert gitutil.commits_touching(git_repo, "a.txt", first) == [second]
    assert gitutil.is_strict_ancestor(git_repo, first, second)
    assert not gitutil.is_strict_ancestor(git_repo, second, second)
    assert not gitutil.is_strict_ancestor(git_repo, second, first)
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert gitutil.sha256_text("") == empty
    (git_repo / "empty").write_bytes(b"")
    assert gitutil.sha256_file(git_repo / "empty") == empty
    with pytest.raises(gitutil.GitError):
        gitutil.git(git_repo, "not-a-command")


def test_wilson_interval() -> None:
    lo, hi = ship_check.wilson(95, 100)
    assert 0.88 < lo < 0.9 and 0.97 < hi < 0.99
    assert ship_check.wilson(0, 0) == (0.0, 1.0)
    assert ship_check.wilson(10, 10)[1] == pytest.approx(1.0)
    assert ship_check.fmt_ci(1, 2).startswith("0.500[")


def test_type_ignore_reason_rule() -> None:
    source = (
        "a = f()  # type: ignore[no-untyped-call]  # third-party stub missing\n"
        "b = f()  # type: ignore\n"
        "c = f()  # type: ignore[attr-defined]\n"
        "d = '# type: ignore inside a string is not a comment'\n"
    )
    assert ship_check.unexplained_type_ignores(source) == [2, 3]
    assert ship_check.unexplained_type_ignores("x = (\n") == [0]


def test_tree_hash_and_text_helpers(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_text("1")
    first = ship_check.tree_sha256(tmp_path)
    (tmp_path / "a" / "f.txt").write_text("2")
    assert ship_check.tree_sha256(tmp_path) != first
    assert ship_check.headings("# A\ntext\n## B c\n") == ["a", "b c"]
    assert ship_check.strip_code("x\n```\n# not heading\n```\ny") == "x\n\ny"
    assert ship_check.one_line("a\n  b\tc") == "a b c"


def test_pre_phase(git_repo: Path, commit: Commit) -> None:
    (git_repo / ".gitignore").write_text("private/\n")
    commit(git_repo, "ignore")
    assert ship_check.pre_phase(git_repo) == {}
    (git_repo / "stray.txt").write_text("x")
    assert "clean" in ship_check.pre_phase(git_repo)
    (git_repo / "stray.txt").unlink()
    (git_repo / "private").mkdir()
    (git_repo / "private" / "held.txt").write_text("secret data")
    manifest = git_repo / "artifacts" / "private_manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"files": {"private/held.txt": "0" * 64, "x.txt": "0"}}))
    commit(git_repo, "manifest")
    problems = ship_check.pre_phase(git_repo)
    assert "manifest" in problems
    (git_repo / ".gitignore").write_text("")
    commit(git_repo, "tracks private")
    problems = ship_check.pre_phase(git_repo)
    assert "private" in problems and "private-ignore" in problems
