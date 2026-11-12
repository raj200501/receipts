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
    (git_repo / "docs").mkdir()
    (git_repo / claimcheck.ALLOW_FILE).write_text("--max-turns 40 | the turn cap, a design value\n")
    doc = git_repo / "README.md"
    doc.write_text(
        "# receipts\n\n"
        "The false-success rate was <!--n:e1.fsr-->0.23<!--/n--> (G7, RQ1, M3, E0, v1.0).\n"
        "See section 10.2 and steps 3 to 5 of the study (2026), run on 2026-10-23.\n"
        "1. first item\n\n```bash\nexit 1\n```\nUse `--max-turns 40` and https://x.org/2510.20270.\n"
    )
    problems, note = claimcheck.check_document(git_repo, "README.md")
    assert problems == []
    assert note == "1 bound number(s)"


def flagged(text: str, allow: tuple[str, ...] = ()) -> list[str]:
    """The quoted numbers that unbound_numbers reports for ``text``."""
    return [
        str(p).split(" ", 3)[-1].split("'")[1]
        for p in claimcheck.unbound_numbers("doc.md", text, list(allow))
    ]


# Every document below is a small synthetic Markdown text, not a real report.


def test_bare_four_digit_counts_are_not_years() -> None:
    """H34: a count from 1900 to 2099 needs a marker; dates and citation years do not."""
    assert flagged("E1 produced 2013 claims.\nThe rate was 1999 of 2050 runs.\n") == [
        "2013",
        "1999",
        "2050",
    ]
    assert flagged("The count rose by 2013. It came from 2013, then 2049 in all\nruns.\n") == [
        "2013",
        "2013",
        "2049",
    ]
    dates = (
        "Run on 2026-10-23, in October 2026, on 23 October 2026, and on Oct. 23, 2026.\n"
        "MASK (2025) and Smith et al., 2024 and (Jones, 2025a; Lee et al. 2023b).\n"
        "Since 2024, agents report more; this held until 2026.\nCopyright (c) 2026 Raj.\n"
    )
    assert flagged(dates) == []


def test_leading_dot_decimals_and_letter_glued_counts() -> None:
    """H35: '.23', 'p95', 'n240', and 'k5' are numbers; identifiers are not."""
    text = "The false-success rate was .23 overall.\nIt reached p95 and n240 runs; k5 too.\n"
    assert flagged(text) == [".23", "p95", "n240", "k5"]
    ids = "SHA256 over utf8 on x86_64 and k8s; G5, N1, RQ1, v1.2, py311, and P2P.\n"
    assert flagged(ids) == []


def test_emphasis_ellipses_and_fractions_cannot_hide_numbers() -> None:
    """Review of H34/H35: underscore emphasis, an ellipsis, or a fraction sign hides nothing."""
    assert flagged("Rate was _42%_ overall.\nRate was __42__ runs.\nRate...42% overall.\n") == [
        "42%",
        "42",
        "42%",
    ]
    assert flagged("about \N{VULGAR FRACTION ONE HALF} of runs\n") == [
        "\N{VULGAR FRACTION ONE HALF}"
    ]
    fractions = (
        "\N{VULGAR FRACTION THREE QUARTERS} of runs failed; 1\N{VULGAR FRACTION ONE THIRD}.\n"
    )
    assert flagged(fractions) == [
        "\N{VULGAR FRACTION THREE QUARTERS}",
        "1\N{VULGAR FRACTION ONE THIRD}",
    ]
    assert flagged("_n240_ runs, _nine_ agents; __Half__ failed. It was high.42% here.\n") == [
        "n240",
        "nine",
        "Half",
        "42%",
    ]
    # Identifiers keep their digits: an underscore between letters or digits is not emphasis.
    ids = (
        "x86_64, run_0042, foo__42, v1.2.3, python3.11, claim\N{SUPERSCRIPT ONE}, "
        "R\N{SUPERSCRIPT TWO}, v2.0.0-rc.1, v2.8.0-beta.3+build.7, and Fig.3; "
        "in _October 2026_.\n"
    )
    assert flagged(ids) == []
    # A version tag after a bare number is not a v-version, and a range hides neither end.
    assert flagged("Use rc.10 or 2.0.0-rc.2 for k = 1..5.\n") == ["10", "2.0", "2", "1", "5"]
    # A version tag never swallows a glued count.
    assert flagged("v1.0-p95, v2+n240, and v1.2.3-k5 runs\n") == ["p95", "n240", "k5"]
    problems = claimcheck.unbound_numbers("doc.md", "a\n\nRate _42%_\n\n\n__7__", [])
    assert [str(p) for p in problems] == [
        "doc.md:3: unbound number '42%'",
        "doc.md:6: unbound number '7'",
    ]
    # Blanked emphasis does not make a list item: "2._fast_" renders as "2.fast".
    assert flagged(
        "2._fast_ runs\n\n\N{DIGIT ZERO}. item\n\N{ARABIC-INDIC DIGIT FOUR}. item\n"
    ) == [
        "2",
        "\N{ARABIC-INDIC DIGIT FOUR}",
    ]


def test_inline_code_and_output_blocks_are_scanned() -> None:
    """H36: numbers in code spans and in output blocks are checked like prose."""
    text = (
        "The false-success rate was `0.23` in the sonnet arm.\n\n"
        "```\nfalse_success_rate 0.23 [0.18, 0.29]\n```\n\n"
        "```text\nrecall 0.91\n```\n\n"
        "```console\n$ make demo --depth 2 \\\n    --seed 7\nprecision 0.97\n```\n\n"
        "```bash\nclaude -p --max-turns 25\n```\n\n"
        "```python\nthreshold = 0.95\n```\n\n"
        '```json\n{"estimate": 0.31}\n```\n\n'
        "See `prereg/0001-e1-main-study.md` and artifacts/studies/e1/runs/0042/run.json.\n"
    )
    assert flagged(text) == ["0.23", "0.23", "0.18", "0.29", "0.91", "0.97", "0.31"]


def test_shell_scripts_sessions_and_paths() -> None:
    """Scripts are skipped, session output is checked, paths are identifiers."""
    assert flagged("```bash\nmake demo\n...\nclaude -p --max-turns 25\n```\n") == []
    assert flagged("```pycon\n>>> rate(\n...     7)\n0.23\n```\n") == ["0.23"]
    paths = ("prereg/0001-x.md", "run.json", "./tools/x.py", "/opt/models/q-7b.gguf", "src/")
    assert all(claimcheck.is_path(t) for t in paths)
    numbers = ("42/60", "runs/42", "0.23/run", "1.5B", "0.23.Next", "e1/0.23")
    assert not any(claimcheck.is_path(t) for t in numbers)
    assert flagged("The rate was 0.23/run and 1.7 claims/run.\n") == ["0.23", "1.7"]


def test_line_start_numbers_need_list_or_section_context() -> None:
    """H44: a wrapped sentence or a heading cannot hide a result number."""
    text = (
        "The number of false-success runs in the sonnet arm was\n17. That is high.\n"
        "### 41% of reports contain a contradicted claim\n"
        "## 12 runs failed\n"
        "## 1.00 precision\n"
    )
    assert flagged(text) == ["17", "41%", "12", "1.00"]
    ok = (
        "## 6. Definition of Done\n### 10.2 Loop Protocol\n#### 1.2.3 Detail\n\n"
        "Steps:\n\n3. first item\n   more text\n4. second item\nlazy line\n5. third\n\n"
        "A paragraph.\n1. a list may interrupt a paragraph\n2. and go on\n"
        "## Steps\n7. a list right after a heading\n"
    )
    assert flagged(ok) == []


def test_number_words_are_checked() -> None:
    """H45: counts written in words need a marker or an allow-list phrase."""
    text = "Nine of ten agents overclaimed.\nHalf were wrong, twice as often; a threefold rise.\n"
    assert flagged(text) == ["Nine", "ten", "Half", "twice", "threefold"]
    ok = "One command runs it; no one often minds. This is a one-off.\n"
    assert flagged(ok) == []
    allow = ("at least two model families",)
    assert flagged("We used at least two model families.\n", allow) == []


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


def test_freshness_with_stub_report(
    git_repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The registry's source here is a SYNTHETIC stand-in for artifacts/e1/results.json,
    # not an analysis output, so the re-derivation of the derived artifacts (DECISIONS
    # D65) is given its outcome; tests/report/test_derived.py runs freshness with the real
    # derivations.
    found: list[str] = []
    monkeypatch.setattr(freshness, "check_derived", lambda root: list(found))
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
    assert "derived artifacts: each equals a fresh derivation" in capsys.readouterr().out
    found.append("artifacts/e1/results.json: differs from a fresh derivation (SYNTHETIC)")
    assert freshness.main(["--root", str(git_repo), "README.md"]) == 1
    assert f"problem: {found[0]}" in capsys.readouterr().out
    found.clear()
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


def test_citecheck_clone_url_is_not_a_reference() -> None:
    """H41: this repository's clone URL is a self link, not a citation (synthetic text)."""
    text = (
        "git clone https://github.com/raj200501/receipts.git && cd receipts\n"
        "See https://github.com/raj200501/receipts/tree/main and "
        "https://github.com/raj200501/receipts-hook and https://github.com/raj200501/receipts.gitx\n"
    )
    assert citecheck.cited_urls(text) == [
        "https://github.com/raj200501/receipts-hook",
        "https://github.com/raj200501/receipts.gitx",
    ]


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
