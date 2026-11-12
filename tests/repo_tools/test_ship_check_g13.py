"""Gate G13 of tools/ship_check.py on synthetic documents (H37 to H40, H46 to H48).

Every README, REPORT, figure, and artifact here is SYNTHETIC, written only to exercise
``ship_check.g13``; the numbers in them are placeholders, not model or real-world
results. ``make reproduce`` and ``make citecheck`` are stubs that print a verdict.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import ship_check

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")

FINDING = (
    "Agents overstated their results in <!--n:e1.fsr-->0.23<!--/n--> of runs"
    " (95% CI <!--n:e1.fsr.ci-->[0.18, 0.29]<!--/n-->)."
)
README = f"""\
# receipts

{FINDING}

![Headline figure](docs/figures/headline.svg)

| Agent | False success |
| --- | --- |
| synthetic | <!--n:e1.fsr-->0.23<!--/n--> |

## Quickstart

```sh
make setup
make demo
```

## What it is and is not

A synthetic README for the G13 tests.

## Key results

Rates come from [the E1 results](artifacts/e1/results.json) under
[the preregistration](prereg/0001-e1.md).

## How it works

![Pipeline diagram](docs/figures/pipeline.svg)

## Use it on your own agent

Synthetic text.

## Reproduce every figure

Run the reproduce target.

## Limitations

Synthetic text.

## Responsible disclosure

Synthetic text.

## Related work

Synthetic text.

## Citation

Synthetic text.

## License

MIT.
"""
FILLER = " ".join(["word"] * 4100)
REPORT = f"""\
# Synthetic technical report

## Abstract

A synthetic report for the G13 tests.

## Introduction

{FILLER}

## Related work

Synthetic text.

## Method

Synthetic text.

## Experiments

Synthetic text.

## Results

The false success rate was <!--n:e1.fsr-->0.23<!--/n-->
(95% CI <!--n:e1.fsr.ci-->[0.18, 0.29]<!--/n-->).

![False success by agent](figures/headline.svg)

## Limitations

Synthetic text.

## Ethics and disclosure

Synthetic text.

## Reproducibility

Synthetic text.
"""
MAKEFILE = """\
# SYNTHETIC test project for tools/ship_check.py gate G13 (stub targets).
PY ?= 3.11
PYTEST_ARGS ?=

setup:
\t@true

reproduce:
\t{reproduce}

citecheck:
\t@echo "CITECHECK: PASS"
"""
REPRODUCE_PASS = '@echo "REPRODUCE: PASS"'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>\n'


def project(
    root: Path,
    readme: str = README,
    report: str = REPORT,
    reproduce: str = REPRODUCE_PASS,
) -> ship_check.Context:
    """Write a SYNTHETIC G13 project into ``root`` and return its Context."""
    files = {
        "README.md": readme,
        "docs/BUILD_BRIEF.md": "Synthetic brief (not the README).\n",
        "docs/REPORT.md": report,
        "docs/figures/headline.svg": SVG,
        "docs/figures/pipeline.svg": SVG,
        "artifacts/report/manifest.json": json.dumps(
            {"figures": ["docs/figures/headline.svg"], "files": {}}
        ),
        "artifacts/e1/results.json": "{}\n",
        "prereg/0001-e1.md": "Synthetic preregistration.\n",
        "Makefile": MAKEFILE.format(reproduce=reproduce),
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    logs = root / "logs"
    logs.mkdir()
    return ship_check.Context(orig=root, clone=root, logs=logs, fast=False, sha="0" * 40)


def edit(text: str, *pairs: tuple[str, str]) -> str:
    """``text`` with each ``(old, new)`` replacement applied exactly once."""
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def test_synthetic_documents_pass(tmp_path: Path) -> None:
    assert "README follows section 11" in ship_check.g13(project(tmp_path))


def test_brief_as_readme_fails(tmp_path: Path) -> None:
    ctx = project(tmp_path)
    (tmp_path / "README.md").write_text("Synthetic brief (not the README).\n", encoding="utf-8")
    with pytest.raises(ship_check.GateError, match="still the build brief"):
        ship_check.g13(ctx)


# ---------------------------------------------------------------- H37 (old code: PASS)


def test_comment_lines_in_code_are_not_headings(tmp_path: Path) -> None:
    readme = edit(
        README,
        ("## Key results\n", ""),
        ("## Reproduce every figure\n", ""),
        (
            "make setup\n",
            "# results: rebuild them with\n# reproduce every figure and number\nmake setup\n",
        ),
    )
    with pytest.raises(ship_check.GateError, match="README lacks sections: result, reproduc"):
        ship_check.g13(project(tmp_path, readme=readme))


def test_report_headings_inside_code_do_not_count(tmp_path: Path) -> None:
    report = edit(REPORT, ("## Results\n", "```text\n# Results table\n```\n"))
    with pytest.raises(ship_check.GateError, match=r"REPORT\.md lacks sections: result"):
        ship_check.g13(project(tmp_path, report=report))


# ---------------------------------------------------------------- H38 (old code: PASS)


def test_finding_needs_its_interval(tmp_path: Path) -> None:
    readme = edit(
        README,
        (FINDING, "Agents overstated their results in <!--n:e1.fsr-->0.23<!--/n--> of runs."),
        ("make demo\n", "make demo\nmake ci\n"),
    )
    with pytest.raises(ship_check.GateError, match="lacks a bound finding with its interval"):
        ship_check.g13(project(tmp_path, readme=readme))


def test_report_results_need_an_interval(tmp_path: Path) -> None:
    report = edit(REPORT, ("\n(95% CI <!--n:e1.fsr.ci-->[0.18, 0.29]<!--/n-->).", "."))
    with pytest.raises(ship_check.GateError, match="results state no interval"):
        ship_check.g13(project(tmp_path, report=report))


@pytest.mark.parametrize(
    "sentence",
    [
        "Agents overstated results in <!--n:e1.fsr-->0.23<!--/n--> of runs (95% CI"
        " <!--n:e1.fsr.ci_low-->0.18<!--/n--> to <!--n:e1.fsr.ci_high-->0.29<!--/n-->).",
        "Agents overstated results in <!--n:e1.fsr-->0.23<!--/n--> of runs (interval"
        " <!--n:e1.fsr.ci-->0.18 to 0.29<!--/n-->).",
        "Agents overstated results in <!--n:e1.fsr-->0.23 [0.18, 0.29]<!--/n--> of runs.",
    ],
)
def test_other_interval_spellings_pass(tmp_path: Path, sentence: str) -> None:
    readme = edit(README, (FINDING, sentence))
    assert "README follows section 11" in ship_check.g13(project(tmp_path, readme=readme))


# ---------------------------------------------------------------- H39 (old code: PASS)


def test_stale_figure_fails_reproduce(tmp_path: Path) -> None:
    reproduce = (
        '@echo "problem: docs/figures/headline.svg: differs from a fresh rebuild";'
        ' echo "REPRODUCE: FAIL 1"; exit 1'
    )
    with pytest.raises(ship_check.GateError, match="make reproduce"):
        ship_check.g13(project(tmp_path, reproduce=reproduce))


# ---------------------------------------------------------------- H40 (old code: PASS)


def test_report_needs_a_generated_figure(tmp_path: Path) -> None:
    report = edit(REPORT, ("![False success by agent](figures/headline.svg)\n", ""))
    with pytest.raises(ship_check.GateError, match=r"REPORT\.md shows no figure"):
        ship_check.g13(project(tmp_path, report=report))


def test_report_figure_must_come_from_make_report(tmp_path: Path) -> None:
    report = edit(REPORT, ("(figures/headline.svg)", "(figures/pipeline.svg)"))
    with pytest.raises(ship_check.GateError, match=r"REPORT\.md shows no figure"):
        ship_check.g13(project(tmp_path, report=report))


# ---------------------------------------------------------------- H46 (old code: PASS)


def test_key_results_link_their_artifact(tmp_path: Path) -> None:
    readme = edit(README, ("[the E1 results](artifacts/e1/results.json)", "the E1 results"))
    with pytest.raises(ship_check.GateError, match="link to no artifact"):
        ship_check.g13(project(tmp_path, readme=readme))


def test_key_results_link_their_preregistration(tmp_path: Path) -> None:
    readme = edit(README, ("[the preregistration](prereg/0001-e1.md)", "the preregistration"))
    with pytest.raises(ship_check.GateError, match="link to no preregistration"):
        ship_check.g13(project(tmp_path, readme=readme))


LINKED = "[the E1 results](artifacts/e1/results.json), [the preregistration](prereg/0001-e1.md)"
OLD_KEY = (
    "Rates come from [the E1 results](artifacts/e1/results.json) under\n"
    "[the preregistration](prereg/0001-e1.md).\n"
)


@pytest.mark.parametrize(
    ("section", "match"),
    [
        pytest.param(
            f"- A SYNTHETIC rate of <!--n:e1.fsr-->0.23<!--/n-->; see {LINKED}.\n"
            "- Another SYNTHETIC rate, <!--n:e1.fsr-->0.23<!--/n-->, with no links.\n",
            r"key result links to no artifact under artifacts/: '- Another SYNTHETIC rate",
            id="second-bullet-unlinked",
        ),
        pytest.param(
            f"{LINKED}.\n\nThe SYNTHETIC rate was <!--n:e1.fsr-->0.23<!--/n-->.\n",
            r"key result links to no artifact",
            id="links-only-in-another-paragraph",
        ),
        pytest.param(
            "- A SYNTHETIC rate of <!--n:e1.fsr-->0.23<!--/n-->; see "
            "[the E1 results](artifacts/e1/results.json).\n"
            "- Its preregistration: [the preregistration](prereg/0001-e1.md).\n",
            r"key result links to no preregistration under prereg/",
            id="prereg-in-a-sibling-bullet",
        ),
        pytest.param(
            f"{LINKED}.\n\n| Rate | Value |\n| --- | --- |\n"
            "| SYNTHETIC | <!--n:e1.fsr-->0.23<!--/n--> |\n",
            r"key result links to no artifact",
            id="table-without-links",
        ),
    ],
)
def test_each_key_result_links_its_artifact_and_preregistration(
    tmp_path: Path, section: str, match: str
) -> None:
    readme = edit(README, (OLD_KEY, section))
    with pytest.raises(ship_check.GateError, match=match):
        ship_check.g13(project(tmp_path, readme=readme))


def test_nested_items_belong_to_their_linked_parent(tmp_path: Path) -> None:
    section = (
        f"- SYNTHETIC rates; see {LINKED}:\n"
        "  - one arm: <!--n:e1.fsr-->0.23<!--/n-->\n"
        "  - and its interval <!--n:e1.fsr.ci-->[0.18, 0.29]<!--/n-->\n"
        "- A SYNTHETIC note without numbers.\n"
    )
    ship_check.g13(project(tmp_path, readme=edit(README, (OLD_KEY, section))))
    items = ship_check.result_items(section)
    assert len(items) == 2 and "one arm" in items[0]


def test_links_to_missing_files_do_not_count(tmp_path: Path) -> None:
    readme = edit(README, ("(artifacts/e1/results.json)", "(artifacts/e1/gone.json)"))
    with pytest.raises(ship_check.GateError, match="link to no artifact"):
        ship_check.g13(project(tmp_path, readme=readme))


ARTIFACT_LINK = "[the E1 results](artifacts/e1/results.json)"
PREREG_LINK = "[the preregistration](prereg/0001-e1.md)"
RATE = "- A SYNTHETIC rate of <!--n:e1.fsr-->0.23<!--/n-->; see "


@pytest.mark.parametrize(
    ("links", "match"),
    [
        pytest.param(
            f"<!-- {ARTIFACT_LINK} --> {PREREG_LINK}", "no artifact", id="artifact-in-a-comment"
        ),
        pytest.param(
            f"{ARTIFACT_LINK} <!-- {PREREG_LINK} -->",
            "no preregistration",
            id="prereg-in-a-comment",
        ),
        pytest.param(
            f"{PREREG_LINK} <!--\n{ARTIFACT_LINK}\n-->",
            "no artifact",
            id="artifact-in-a-multi-line-comment",
        ),
        pytest.param(
            f"`{ARTIFACT_LINK}` and {PREREG_LINK}", "no artifact", id="artifact-in-inline-code"
        ),
        pytest.param(
            f"{ARTIFACT_LINK} and ``{PREREG_LINK}``", "no preregistration", id="prereg-in-code"
        ),
        pytest.param(
            f"[the E1 directory](artifacts/e1/) and {PREREG_LINK}",
            "no artifact",
            id="artifact-directory",
        ),
        pytest.param(
            f"{ARTIFACT_LINK} and [the lock](prereg/LOCK.json)",
            "no preregistration",
            id="prereg-lock-file",
        ),
        pytest.param(
            f"{ARTIFACT_LINK} and [notes](prereg/notes/0001-e1.md)",
            "no preregistration",
            id="prereg-in-a-subdirectory",
        ),
        pytest.param(
            f"{ARTIFACT_LINK} and [a draft](prereg/draft-e1.md)",
            "no preregistration",
            id="prereg-without-its-number",
        ),
    ],
)
def test_key_result_links_count_only_in_visible_prose_and_to_real_files(
    tmp_path: Path, links: str, match: str
) -> None:
    # The first paragraph links both properly, so the section as a whole passes and
    # only the per-item rule can catch the key result below it.
    section = f"{LINKED}.\n\n{RATE}{links}.\n"
    ctx = project(tmp_path, readme=edit(README, (OLD_KEY, section)))
    for rel in ("prereg/LOCK.json", "prereg/notes/0001-e1.md", "prereg/draft-e1.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ship_check.GateError, match=f"README key result links to {match}"):
        ship_check.g13(ctx)


@pytest.mark.parametrize(
    "section",
    [
        pytest.param(f"Rates: <!-- {LINKED} -->.\n", id="comment"),
        pytest.param(f"Rates: `{LINKED}`.\n", id="inline-code"),
        pytest.param(
            "Rates: [results](artifacts/e1/) under [the lock](prereg/LOCK.json).\n",
            id="directory-and-lock",
        ),
    ],
)
def test_key_results_section_links_count_only_in_visible_prose(
    tmp_path: Path, section: str
) -> None:
    ctx = project(tmp_path, readme=edit(README, (OLD_KEY, section)))
    (tmp_path / "prereg" / "LOCK.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ship_check.GateError, match="README key results link to no"):
        ship_check.g13(ctx)


def test_links_with_code_in_their_text_count(tmp_path: Path) -> None:
    section = (
        f"{RATE}[`artifacts/e1/results.json`](artifacts/e1/results.json) and "
        "[`prereg/0001-e1.md`](prereg/0001-e1.md).\n"
    )
    assert "README follows section 11" in ship_check.g13(
        project(tmp_path, readme=edit(README, (OLD_KEY, section)))
    )


def test_how_it_works_needs_a_diagram(tmp_path: Path) -> None:
    readme = edit(README, ("![Pipeline diagram](docs/figures/pipeline.svg)", "Synthetic text."))
    with pytest.raises(ship_check.GateError, match="no diagram"):
        ship_check.g13(project(tmp_path, readme=readme))


def test_mermaid_diagram_counts(tmp_path: Path) -> None:
    readme = edit(
        README,
        ("![Pipeline diagram](docs/figures/pipeline.svg)", "```mermaid\ngraph LR\n  a --> b\n```"),
    )
    assert "README follows section 11" in ship_check.g13(project(tmp_path, readme=readme))


def test_quickstart_may_run_the_demo_script_directly(tmp_path: Path) -> None:
    readme = edit(README, ("make demo\n", "uv run python tools/demo.py\n"))
    assert "README follows section 11" in ship_check.g13(project(tmp_path, readme=readme))


def test_quickstart_runs_the_offline_demo(tmp_path: Path) -> None:
    readme = edit(README, ("make demo\n", "claude -p 'summarize'\n"))
    with pytest.raises(ship_check.GateError, match="does not run make demo"):
        ship_check.g13(project(tmp_path, readme=readme))


# ---------------------------------------------------------------- H47 (old code: PASS)


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("# receipts\n", "# receipts\n\nreceipts &mdash; a verifier.\n", "em dash"),
        ("# receipts\n", "# receipts\n\nreceipts &#8212; a verifier.\n", "em dash"),
        ("# receipts\n", "# receipts\n\nreceipts &#x2014; a verifier.\n", "em dash"),
        ("A synthetic README", "A state of\nthe art README", "hype"),
        ("A synthetic README", "A ground-breaking README", "hype"),
        ("A synthetic README", "A SOTA README", "hype"),
    ],
)
def test_em_dash_entities_and_wrapped_hype_fail(
    tmp_path: Path, old: str, new: str, match: str
) -> None:
    with pytest.raises(ship_check.GateError, match=match):
        ship_check.g13(project(tmp_path, readme=edit(README, (old, new))))


# ---------------------------------------------------------------- H48 (old code: FAIL)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "![Headline figure](docs/figures/headline.svg)",
            "[![ci](https://github.com/example/receipts/actions/workflows/ci.yml/badge.svg)]"
            "(https://github.com/example/receipts/actions)\n\n"
            "![Headline figure](docs/figures/headline.svg)",
        ),
        ("(docs/figures/headline.svg)", "(./docs/figures/headline.svg)"),
        ("(docs/figures/headline.svg)", '(docs/figures/headline.svg "Headline")'),
        (
            "![Headline figure](docs/figures/headline.svg)",
            '<img src="docs/figures/headline.svg" alt="Headline figure">',
        ),
    ],
    ids=["badge-first", "dot-slash", "titled", "img-tag"],
)
def test_headline_figure_spellings_pass(tmp_path: Path, old: str, new: str) -> None:
    readme = edit(README, (old, new))
    assert "README follows section 11" in ship_check.g13(project(tmp_path, readme=readme))


def test_headline_figure_must_be_generated(tmp_path: Path) -> None:
    readme = edit(README, ("(docs/figures/headline.svg)", "(docs/figures/pipeline.svg)"))
    with pytest.raises(ship_check.GateError, match="headline SVG missing"):
        ship_check.g13(project(tmp_path, readme=readme))
