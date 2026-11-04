"""Tests for secrets_scan, budget_report, review, and ship_check helpers."""

from __future__ import annotations

import bz2
import gzip
import hashlib
import io
import json
import lzma
import shutil
import tarfile
import zipfile
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


def test_scan_files_fails_closed_on_unknown_binary(git_repo: Path, commit: Commit) -> None:
    """H33: a binary file of unknown type is a finding, never a silent skip (synthetic)."""
    (git_repo / "a.txt").write_text(f"{FAKE_AWS}\n")
    (git_repo / "b.bin").write_bytes(b"\0\1\2\3" * 64 + FAKE_AWS.encode())
    commit(git_repo, "files")
    findings, scanned = secrets_scan.scan_files(git_repo, ["a.txt", "b.bin", "gone.txt"], {})
    assert scanned == 1
    assert [str(f) for f in findings] == [
        "a.txt:1: aws-access-key-id",
        "b.bin:0: unscannable: binary file of unknown type",
    ]


# Built at runtime so this file never contains a secret-shaped literal.
FAKE_ANT = "sk-" + "ant-api03-" + "A" * 30


def test_scan_reads_large_utf16_utf32_and_compressed_files(tmp_path: Path) -> None:
    """H33: large, UTF-16, UTF-32, gzip, bzip2, xz, zip, and tar files are all read (synthetic)."""
    secret = f"key {FAKE_ANT}\n"
    big = "".join(f'{{"run": {i}, "out": "{"x" * 80}"}}\n' for i in range(60_000)) + secret
    assert len(big) > 5_000_000
    (tmp_path / "runs.jsonl").write_text(big)
    (tmp_path / "u16.txt").write_bytes(("line one\n" + secret).encode("utf-16"))
    (tmp_path / "u16le.txt").write_bytes(("line one\n" + secret).encode("utf-16-le"))
    (tmp_path / "u32.txt").write_bytes(("line one\n" + secret).encode("utf-32"))
    (tmp_path / "t.jsonl.gz").write_bytes(gzip.compress(("{}\n" + secret).encode()))
    (tmp_path / "t.txt.bz2").write_bytes(bz2.compress(secret.encode()))
    (tmp_path / "t.txt.xz").write_bytes(lzma.compress(secret.encode()))
    with zipfile.ZipFile(tmp_path / "a.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("inner/ok.txt", "nothing\n")
        archive.writestr("inner/notes.txt", secret)
    with tarfile.open(tmp_path / "b.tar.gz", "w:gz") as tar:
        data = secret.encode()
        info = tarfile.TarInfo("run/transcript.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    names = sorted(p.name for p in tmp_path.iterdir())
    report = secrets_scan.scan_report(tmp_path, names, {})
    # The key-shaped string also matches the OpenAI-style rule; compare the Anthropic hits.
    assert sorted(str(f) for f in report.findings if f.rule == "anthropic-key") == [
        "a.zip!inner/notes.txt:1: anthropic-key",
        "b.tar.gz!run/transcript.txt:1: anthropic-key",
        "runs.jsonl:60001: anthropic-key",
        "t.jsonl.gz:2: anthropic-key",
        "t.txt.bz2:1: anthropic-key",
        "t.txt.xz:1: anthropic-key",
        "u16.txt:2: anthropic-key",
        "u16le.txt:2: anthropic-key",
        "u32.txt:2: anthropic-key",
    ]
    assert report.scanned == len(names)


def test_scan_raw_types_unsupported_archives_and_bombs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known binary types are read raw and listed; what cannot be read is a finding."""
    png = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + b"\0" * 32
    (tmp_path / "plot.png").write_bytes(png)
    (tmp_path / "leak.png").write_bytes(png + b"tEXt" + FAKE_ANT.encode())
    (tmp_path / "x.zst").write_bytes(b"\x28\xb5\x2f\xfd" + b"\0" * 16)
    (tmp_path / "bomb.gz").write_bytes(gzip.compress(b"a" * 5000))
    (tmp_path / "menu.txt").write_text("x" * 256 + "mustard and more text\n")
    monkeypatch.setattr(secrets_scan, "MAX_EXPANDED", 1000)
    names = ["bomb.gz", "leak.png", "menu.txt", "plot.png", "x.zst"]
    report = secrets_scan.scan_report(tmp_path, names, {})
    assert [str(f) for f in report.findings if f.rule != "openai-style-key"] == [
        "bomb.gz:0: unscannable: content expands past 1000 bytes",
        "leak.png:3: anthropic-key",
        "x.zst:0: unscannable: zstd archive",
    ]
    assert report.raw_only == ["leak.png", "plot.png"]


def test_env_values_that_cannot_be_secrets_are_ignored() -> None:
    """H50: git config key names and file paths in secret-named variables are not secrets."""
    env = {
        "GIT_CONFIG_KEY_0": "credential.interactive",
        "GIT_CONFIG_KEY_1": "url.https://github.com/.insteadOf",
        "CLAUDE_SESSION_INGRESS_TOKEN_FILE": "/home/claude/.session/ingress-token",
        "GOOGLE_APPLICATION_CREDENTIALS": "/etc/gcloud/application-creds.json",
        "MY_API_KEY": "my-long-env-secret-value-123",
        "SERVICE_KEYS": "my-other-long-secret-value-456",
    }
    assert set(secrets_scan.env_secret_values(env)) == {"MY_API_KEY", "SERVICE_KEYS"}
    line = "git -c credential.interactive=never fetch; see url.https://github.com/.insteadOf\n"
    assert secrets_scan.scan_text("sandbox_git.sh", line, secrets_scan.env_secret_values(env)) == []


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


def test_secrets_scan_main_lists_raw_files_and_reads_links(
    git_repo: Path,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing is skipped silently, and the summary line keeps its format (synthetic repo)."""
    monkeypatch.setattr(secrets_scan.os, "environ", {})
    (git_repo / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")
    (git_repo / "notes.txt").write_text("plain\n")
    (git_repo / "link").symlink_to("notes.txt")
    commit(git_repo, "files")
    assert secrets_scan.main(["--root", str(git_repo)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "read as raw bytes only (1): plot.png",
        "SECRETS-SCAN: CLEAN (3 tracked text files)",
    ]
    (git_repo / "link").unlink()
    (git_repo / "link").symlink_to(FAKE_ANT)
    commit(git_repo, "a link whose target is key-shaped")
    assert secrets_scan.main(["--root", str(git_repo)]) == 1
    assert "link:1: anthropic-key" in capsys.readouterr().out


def copy_budget_inputs(root: Path) -> None:
    (root / "docs").mkdir(exist_ok=True)
    for name in ("BUILD_BRIEF.md", "BUILD_BRIEF.sha256"):
        shutil.copy(ROOT / "docs" / name, root / "docs" / name)
    shutil.copy(ROOT / "budget.toml", root / "budget.toml")


def test_budget_report(git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]) -> None:
    copy_budget_inputs(git_repo)
    commit(git_repo, "bootstrap copy of the brief, its hash, and the caps")
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


def test_budget_report_anchors_the_brief(
    git_repo: Path, commit: Commit, capsys: pytest.CaptureFixture[str]
) -> None:
    """H43: raising a cap in both the brief and budget.toml fails (synthetic repo)."""
    copy_budget_inputs(git_repo)
    commit(git_repo, "bootstrap")
    assert budget_report.main(["--root", str(git_repo)]) == 0
    capsys.readouterr()
    brief = git_repo / "docs" / "BUILD_BRIEF.md"
    raised = "claude_agent_runs_per_day = 300"
    brief.write_text(brief.read_text().replace("claude_agent_runs_per_day = 30 ", raised + " "))
    toml = git_repo / "budget.toml"
    toml.write_text(toml.read_text().replace("claude_agent_runs_per_day = 30", raised))
    commit(git_repo, "raise a cap in both places")
    assert budget_report.main(["--root", str(git_repo)]) == 1
    out = capsys.readouterr().out
    assert "violation: docs/BUILD_BRIEF.md does not match docs/BUILD_BRIEF.sha256" in out
    digest = hashlib.sha256(brief.read_bytes()).hexdigest()
    (git_repo / "docs" / "BUILD_BRIEF.sha256").write_text(f"{digest}  BUILD_BRIEF.md\n")
    commit(git_repo, "rewrite the recorded hash too")
    assert budget_report.main(["--root", str(git_repo)]) == 1
    out = capsys.readouterr().out
    assert "violation: docs/BUILD_BRIEF.sha256 changed after its first commit" in out
    assert "does not match" not in out


def test_budget_report_needs_a_committed_hash(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_budget_inputs(git_repo)
    assert budget_report.main(["--root", str(git_repo)]) == 1
    assert "docs/BUILD_BRIEF.sha256 is not committed" in capsys.readouterr().out


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


def test_review_sees_code_moved_into_an_allowed_path(git_repo: Path, commit: Commit) -> None:
    """H49: a rename into artifacts/review/ still counts as a code change (synthetic repo)."""
    (git_repo / "docs").mkdir()
    (git_repo / "docs" / "REVIEW_LOG.md").write_text("- N1: noted\n")
    (git_repo / "src").mkdir()
    (git_repo / "src" / "checkers.py").write_text("def check():\n    return True\n" * 20)
    sha = commit(git_repo, "reviewed code")
    (git_repo / "artifacts" / "review").mkdir(parents=True)
    (git_repo / "src" / "checkers.py").rename(git_repo / "artifacts" / "review" / "old_checkers.py")
    write_review(git_repo, review_doc(sha))
    commit(git_repo, "move the code into the review directory")
    problems = review.validate(git_repo, review_doc(sha))
    assert problems == [f"code changed since the reviewed commit {sha[:12]}: src/checkers.py"], (
        problems
    )
    (git_repo / "STATUS.md").write_text("status\n")
    sha = commit(git_repo, "status only")
    (git_repo / "artifacts" / "review" / "a file with spaces.json").write_text("{}\n")
    commit(git_repo, "review notes")
    assert review.validate(git_repo, review_doc(sha)) == []


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
