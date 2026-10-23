"""Tests for claimcheck, freshness, and citecheck."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import citecheck
import claimcheck
import freshness

Commit = Callable[[Path, str], str]
ROOT = Path(__file__).resolve().parents[2]


def make_registry(root: Path, value: str = "0.23") -> None:
    source = root / "artifacts" / "e1" / "results.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{"x": 1}')
    registry = root / claimcheck.REGISTRY
    registry.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "value": value,
        "source": "artifacts/e1/results.json",
        "source_sha256": claimcheck.sha256_file(source),
        "derivation": "tools/report.py:fsr",
    }
    registry.write_text(json.dumps({"numbers": {"e1.fsr": entry}}))


def test_bound_numbers_and_identifiers_pass(git_repo: Path) -> None:
    make_registry(git_repo)
    doc = git_repo / "README.md"
    doc.write_text(
        "# receipts\n\n"
        "The false-success rate was <!--n:e1.fsr-->0.23<!--/n--> (G7, RQ1, M3, E0, v1.0).\n"
        "See section 10.2 and steps 3 to 5 of the 2026 study, run on 2026-10-23.\n"
        "1. first item\n\n```\nexit 1\n```\nUse `--max-turns 40` and https://x.org/2510.20270.\n"
    )
    problems, note = claimcheck.check_document(git_repo, "README.md")
    assert problems == []
    assert note == "1 bound number(s)"


def test_unbound_and_mismatched_numbers_fail(git_repo: Path) -> None:
    make_registry(git_repo)
    (git_repo / "README.md").write_text(
        "Agents lied in 42% of runs.\nRate <!--n:e1.fsr-->0.25<!--/n-->; "
        "<!--n:e1.none-->1<!--/n-->\n"
    )
    problems, _ = claimcheck.check_document(git_repo, "README.md")
    messages = [str(p) for p in problems]
    assert any("unbound number '42%'" in m for m in messages)
    assert any("shows '0.25'" in m for m in messages)
    assert any("e1.none" in m for m in messages)


def test_changed_or_missing_source(git_repo: Path) -> None:
    make_registry(git_repo)
    (git_repo / "artifacts" / "e1" / "results.json").write_text('{"x": 2}')
    (git_repo / "README.md").write_text("<!--n:e1.fsr-->0.23<!--/n-->\n")
    assert "hash changed" in str(claimcheck.check_document(git_repo, "README.md")[0][0])
    (git_repo / "artifacts" / "e1" / "results.json").unlink()
    assert "missing" in str(claimcheck.check_document(git_repo, "README.md")[0][0])


def test_allow_file_phrases(git_repo: Path) -> None:
    (git_repo / "docs").mkdir()
    allow = git_repo / claimcheck.ALLOW_FILE
    allow.write_text("# design parameters\nat least 60 runs per configuration | G7 design\n")
    (git_repo / "README.md").write_text("We ran at least 60 runs per configuration.\n")
    assert claimcheck.check_document(git_repo, "README.md")[0] == []
    allow.write_text("no reason here\n")
    with pytest.raises(ValueError, match="phrase"):
        claimcheck.check_document(git_repo, "README.md")


def test_brief_identical_doc_is_exempt_and_missing_doc_fails(git_repo: Path) -> None:
    (git_repo / "docs").mkdir()
    (git_repo / "docs" / "BUILD_BRIEF.md").write_text("30 to 60 tasks\n")
    (git_repo / "README.md").write_text("30 to 60 tasks\n")
    assert claimcheck.check_document(git_repo, "README.md") == (
        [],
        "identical to the build brief (exempt)",
    )
    problems, note = claimcheck.check_document(git_repo, "docs/REPORT.md")
    assert note == "missing" and problems


def test_registry_must_be_object(git_repo: Path) -> None:
    (git_repo / "artifacts" / "report").mkdir(parents=True)
    (git_repo / claimcheck.REGISTRY).write_text('{"numbers": []}')
    with pytest.raises(ValueError):
        claimcheck.load_registry(git_repo)


def test_claimcheck_main(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (git_repo / "README.md").write_text("plain words\n")
    assert claimcheck.main(["--root", str(git_repo), "README.md"]) == 0
    assert claimcheck.main(["--root", str(git_repo), "README.md", "docs/REPORT.md"]) == 1
    out = capsys.readouterr().out
    assert "CLAIMCHECK: FAIL 1" in out
    (git_repo / "docs").mkdir()
    (git_repo / claimcheck.ALLOW_FILE).write_text("bad\n")
    assert claimcheck.main(["--root", str(git_repo), "README.md"]) == 1


def test_compare_registries() -> None:
    a = {"k": {"value": "1"}, "gone": {"value": "2"}}
    b = {"k": {"value": "3"}, "new": {"value": "4"}}
    problems = freshness.compare_registries(a, b)
    assert len(problems) == 3
    assert freshness.compare_registries(a, a) == []


def test_freshness_with_stub_report(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (git_repo / "README.md").write_text("<!--n:e1.fsr-->0.23<!--/n-->\n")
    assert freshness.main(["--root", str(git_repo), "README.md"]) == 1
    assert "tools/report.py is missing" in capsys.readouterr().out
    make_registry(git_repo)
    tools = git_repo / "tools"
    tools.mkdir()
    registry = (git_repo / claimcheck.REGISTRY).read_text()
    (tools / "report.py").write_text(
        "import sys, pathlib\n"
        f"pathlib.Path(sys.argv[sys.argv.index('--out') + 1]).write_text({registry!r})\n"
    )
    assert freshness.main(["--root", str(git_repo), "README.md"]) == 0
    (git_repo / "README.md").write_text("<!--n:e1.fsr-->0.99<!--/n-->\n")
    assert freshness.main(["--root", str(git_repo), "README.md", "docs/REPORT.md"]) == 1
    out = capsys.readouterr().out
    assert "rebuilt '0.23'" in out and "docs/REPORT.md: document is missing" in out
    (tools / "report.py").write_text("raise SystemExit('boom')\n")
    assert freshness.main(["--root", str(git_repo), "README.md"]) == 1
    assert "failed: boom" in capsys.readouterr().out


def test_freshness_exempts_brief(git_repo: Path) -> None:
    (git_repo / "docs").mkdir()
    (git_repo / "docs" / "BUILD_BRIEF.md").write_text("brief\n")
    (git_repo / "README.md").write_text("brief\n")
    assert freshness.main(["--root", str(git_repo), "README.md"]) == 0


def citation(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "key": "mask",
        "title": "MASK",
        "authors": ["A"],
        "year": 2025,
        "url": "https://arxiv.org/abs/2503.03750",
        "final_url": "https://arxiv.org/abs/2503.03750v2",
        "page_title": "MASK",
        "retrieved": "2026-10-23",
        "content_sha256": "a" * 64,
        "status": "verified",
    }
    return {**base, **over}


def test_citecheck(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = ["--root", str(git_repo)]
    (git_repo / "README.md").write_text(
        "See https://arxiv.org/abs/2503.03750. Repo: "
        "https://github.com/raj200501/receipts/tree/main\n"
    )
    assert citecheck.main([*root, "README.md"]) == 1
    assert "missing" in capsys.readouterr().out
    (git_repo / "artifacts").mkdir()
    cite = git_repo / citecheck.CITECHECK
    cite.write_text(json.dumps({"references": [citation()]}))
    assert citecheck.main([*root, "README.md"]) == 0
    cite.write_text(json.dumps({"references": [citation(status="dropped")]}))
    assert citecheck.main([*root, "README.md"]) == 1
    assert "dropped reference" in capsys.readouterr().out
    cite.write_text(
        json.dumps({"references": [citation(url="https://other.org", final_url="https://o.org")]})
    )
    assert citecheck.main([*root, "README.md", "docs/REPORT.md"]) == 1
    cite.write_text("{")
    assert citecheck.main([*root, "README.md"]) == 1


def test_citecheck_entry_validation() -> None:
    assert citecheck.validate_entry(citation()) == []
    bad = citation(status="maybe", content_sha256="x", retrieved="today", authors="A", title="")
    problems = citecheck.validate_entry(bad)
    assert len(problems) == 4
    assert citecheck.validate_entry(citation(content_sha256="x")) == [
        "mask: content_sha256 must be 64 lowercase hex characters"
    ]


def test_citecheck_exempts_brief(git_repo: Path) -> None:
    (git_repo / "docs").mkdir()
    (git_repo / "artifacts").mkdir()
    (git_repo / citecheck.CITECHECK).write_text(json.dumps({"references": []}))
    (git_repo / "docs" / "BUILD_BRIEF.md").write_text("https://example.org\n")
    (git_repo / "README.md").write_text("https://example.org\n")
    assert citecheck.check(git_repo, ["README.md"]) == ([], 0)


def test_repo_brief_has_no_em_dash() -> None:
    assert "\N{EM DASH}" not in (ROOT / "docs" / "BUILD_BRIEF.md").read_text()
