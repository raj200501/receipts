"""Robustness of extract_claims on odd input. Every input here is generated test data.

The receipts hook runs extraction on whatever text an agent writes, so extraction must
never raise and every claim must point at its exact text. The fuzz below is seeded, so
it is deterministic.
"""

from __future__ import annotations

import random
import time

import pytest

from receipts.claims import extract_claims

#: Text pieces to combine; chr() spells the non-ASCII ones (check marks, an arrow, curly
#: quotes, an em dash, a no-break space, a bullet) so that the source stays ASCII.
UNICODE = [chr(c) for c in (0x2705, 0x274C, 0x2192, 0x201C, 0x2019, 0x2014, 0x00A0, 0x2022)]
PIECES = [
    "`", "``", "```", "\n", "\n\n", "|", "- ", "* ", "1. ", "# ", "> ", "**", "_", "(", ")",
    ":", ";", ",", ".", "!", "?", " ", "  ", "\t", "\r\n", "[x] ", "tests", "pass", "fail",
    "ran", "Fixed", "added", "`pytest -q`", "src/app.py", "12/13", "0", "42 passed",
    "could not", "didn't", "the", "lint", "mypy", "ruff", "build", "Done.", "all",
    "none of the", "requests>=2.32", "bumped", "to", "from", "in", "README", ".env", "::",
    "@", "v1.2", "\\|", "-->", "<br>", "[a](b)", "~~~", "    ", "Tests:", "| --- |", "e.g.",
    "etc.", *UNICODE,
]  # fmt: skip


def assert_consistent(text: str) -> None:
    claims = extract_claims(text)
    for claim in claims:
        assert text[claim.span[0] : claim.span[1]] == claim.text
    assert [c.claim_id for c in claims] == [f"c{i}" for i in range(len(claims))]


def test_seeded_fuzz_never_raises_and_keeps_spans() -> None:
    rng = random.Random(20261104)
    for _ in range(400):
        assert_consistent("".join(rng.choice(PIECES) for _ in range(rng.randint(0, 60))))


#: Opening words that the filler rules repeat ("So, and also ..."). Each is followed by
#: runs of spaces, the shape that once made the rules backtrack exponentially (8 fillers
#: with 6 spaces each took 30 seconds; Markdown masking turns "**and**" into such runs).
FILLERS = [
    "so", "and", "also", "now", "then", "overall", "however", "unfortunately", "note",
    "okay", "great", "status", "summary", "but", "still", "currently", "caveat", "in short",
]  # fmt: skip


@pytest.mark.parametrize("filler", FILLERS)
@pytest.mark.parametrize("separator", ["      ", "  ,  ", " :   ", " -  "])
def test_runs_of_fillers_and_spaces_stay_fast(filler: str, separator: str) -> None:
    for text in ((filler + separator) * 16 + "x", (filler + separator) * 16 + "the parser"):
        started = time.perf_counter()
        assert_consistent(text)
        assert time.perf_counter() - started < 2.0, repr(text[:40])


def test_markdown_masking_does_not_create_slow_inputs() -> None:
    for text in (
        ("so" + " " * 6) * 12 + "x",
        " ".join(["**and**"] * 20) + " the parser",
        " ".join(["**so**,"] * 20) + " I could not run it",
        " ".join(["<b>so</b>"] * 20) + " done",
        "| " + " | ".join(["and"] * 20) + " | x |",
    ):
        started = time.perf_counter()
        assert_consistent(text)
        assert time.perf_counter() - started < 2.0, repr(text[:40])


@pytest.mark.parametrize(
    "text",
    [
        "updated the parser and " * 400,
        ("word " * 1500) + "fixed the bug.",
        "`a` " * 1000,
        "``` ` `` " * 500,
        "| a | b |\n|---|---|\n" + "| `x.py` | Added |\n" * 300,
        "".join("  " * (i % 40) + f"- item `f{i}.py` updated\n" for i in range(300)),
        "I could not " * 500,
        "tests " * 1000 + "pass",
        ("a, " * 1000) + "and the tests pass",
        " ".join(str(i) for i in range(1000)) + " passed",
        chr(0x2705) * 500,
        "```\n" + "All tests pass.\n" * 100,
    ],
    ids=lambda text: text[:20],
)
def test_large_and_repetitive_reports(text: str) -> None:
    assert_consistent(text)
