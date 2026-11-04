"""Tests for receipts.claims.segment. Every report here is hand-written test input."""

from __future__ import annotations

import pytest

from receipts.claims.segment import (
    CodeBlock,
    Segmentation,
    Unit,
    clean_label,
    code_spans,
    mask_markdown,
    segment,
    split_clauses,
    split_sentences,
    table_cells,
)


def texts(report: str) -> list[str]:
    return [u.text for u in segment(report).units]


def sentences(text: str) -> list[str]:
    return [text[a:b] for a, b in split_sentences(text)]


def clauses(text: str) -> list[str]:
    return [text[a:b] for a, b in split_clauses(text)]


# --- spans ---------------------------------------------------------------------------

HAND_WRITTEN_REPORT = """I implemented the `--json` flag. All tests pass and the linter is clean.

## Changes
- **`src/cli.py`**: added a `--json` argument; output is JSON now.
- [x] Added tests in `tests/test_cli.py`
  covering empty input.
1. Ran `pytest -q`

| File | Change |
| --- | --- |
| `src/cli.py` | Modified |

```bash
$ pytest -q
3 passed
```

> Note: Postgres is not available here.

Done.
"""


def test_every_unit_text_is_its_exact_span() -> None:
    seg = segment(HAND_WRITTEN_REPORT)
    assert isinstance(seg, Segmentation) and seg.report == HAND_WRITTEN_REPORT
    assert seg.units
    for unit in seg.units:
        assert HAND_WRITTEN_REPORT[unit.span[0] : unit.span[1]] == unit.text
        assert unit.text == unit.text.strip()
    starts = [u.span[0] for u in seg.units]
    assert starts == sorted(starts)


def test_units_of_a_mixed_report() -> None:
    assert texts(HAND_WRITTEN_REPORT) == [
        "I implemented the `--json` flag.",
        "All tests pass",
        "the linter is clean.",
        "Changes",
        "**`src/cli.py`**: added a `--json` argument",
        "output is JSON now.",
        "Added tests in `tests/test_cli.py`\n  covering empty input.",
        "Ran `pytest -q`",
        "| `src/cli.py` | Modified |",
        "Note: Postgres is not available here.",
        "Done.",
    ]


def test_unit_kinds_contexts_and_first_flags() -> None:
    units = {u.text: u for u in segment(HAND_WRITTEN_REPORT).units}
    assert units["Changes"].kind == "heading"
    item = units["**`src/cli.py`**: added a `--json` argument"]
    assert item.kind == "list_item" and item.context == "Changes" and item.first
    second = units["output is JSON now."]
    assert second.kind == "list_item" and not second.first and second.block == item.block
    row = units["| `src/cli.py` | Modified |"]
    assert row.kind == "table_row" and row.header == ("file", "change")
    assert units["Done."].kind == "sentence"
    assert units["the linter is clean."].previous == "All tests pass"


def test_fenced_code_is_not_a_unit_but_is_kept() -> None:
    seg = segment(HAND_WRITTEN_REPORT)
    assert all("3 passed" not in u.text for u in seg.units)
    assert seg.code_blocks == (CodeBlock("$ pytest -q\n3 passed", seg.code_blocks[0].span, "bash"),)
    block = seg.code_blocks[0]
    assert HAND_WRITTEN_REPORT[block.span[0] : block.span[1]] == block.text


def test_tilde_and_unclosed_fences() -> None:
    seg = segment("Ran it:\n~~~\nAll tests pass\n~~~\nDone.\n\n```\nstill code")
    assert [u.text for u in seg.units] == ["Ran it:", "Done."]
    assert [b.text for b in seg.code_blocks] == ["All tests pass", "still code"]
    assert segment("```\n```").code_blocks == ()


def test_empty_and_blank_reports() -> None:
    assert segment("").units == ()
    assert segment("   \n\n  ").units == ()
    assert segment("---\n***\n").units == ()


def test_crlf_line_endings_keep_exact_spans() -> None:
    report = "Updated `a.py`.\r\nAll tests pass.\r\n\r\n- Done\r\n"
    seg = segment(report)
    assert [u.text for u in seg.units] == ["Updated `a.py`.", "All tests pass.", "Done"]
    for unit in seg.units:
        assert report[unit.span[0] : unit.span[1]] == unit.text


# --- sentences -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Updated config.py. All tests pass.", ["Updated config.py.", "All tests pass."]),
        ("Bumped lodash to 4.17.21. Done!", ["Bumped lodash to 4.17.21.", "Done!"]),
        ("It took 0.8s. Then I stopped.", ["It took 0.8s.", "Then I stopped."]),
        ("Is it fixed? Yes.", ["Is it fixed?", "Yes."]),
        ("Use a flag, e.g. `--json`. Done.", ["Use a flag, e.g. `--json`.", "Done."]),
        ("Formats (i.e. JSON) work. Done.", ["Formats (i.e. JSON) work.", "Done."]),
        ("I fixed a, b, etc. and more.", ["I fixed a, b, etc. and more."]),
        ("I fixed a, b, etc. Then I left.", ["I fixed a, b, etc.", "Then I left."]),
        ("Ran `pytest -q; echo ok. Done`. Next.", ["Ran `pytest -q; echo ok. Done`.", "Next."]),
        ('He said "done." Then left.', ['He said "done."', "Then left."]),
        ("Waiting... Done.", ["Waiting...", "Done."]),
        ("version 2. nothing else", ["version 2. nothing else"]),
        ("Ran tests.✅ Done.", ["Ran tests.✅ Done."]),
        ("Fixed it. ✅ All green.", ["Fixed it.", "✅ All green."]),
        ("Done.   ", ["Done."]),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert sentences(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Changes:\nUpdated a.py", ["Changes:", "Updated a.py"]),
        ("Updated config.py\nAdded tests", ["Updated config.py", "Added tests"]),
        ("I updated the parser and added\na regression test.", None),
        ("I ran the suite with\n`pytest -q` and it passed.", None),
        ("Updated the loader in\nsrc/config.py today", None),
        ("Fixed the bug,\nAdded tests", None),
    ],
)
def test_line_breaks(text: str, expected: list[str] | None) -> None:
    assert sentences(text) == (expected if expected is not None else [text])


def test_split_sentences_with_offsets_and_punctuation_only_pieces() -> None:
    text = "xx Done. Ok. yy"
    assert split_sentences(text, 3, 12) == [(3, 8), (9, 12)]
    assert split_sentences("...") == []
    assert split_sentences("Done.\n✅") == [(0, 5)]


# --- clauses -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("All tests pass and the build succeeds", ["All tests pass", "the build succeeds"]),
        ("Updated `a.py` and `b.py`", ["Updated `a.py` and `b.py`"]),
        ("Ran pytest and mypy", ["Ran pytest and mypy"]),
        ("Ran ruff and mypy reports no errors", ["Ran ruff", "mypy reports no errors"]),
        (
            "Fixed the bug, added a test, and ran the suite",
            ["Fixed the bug", "added a test", "ran the suite"],
        ),
        ("Updated the parser; tests pass", ["Updated the parser", "tests pass"]),
        ("Ran the tests and they all pass", ["Ran the tests and they all pass"]),
        ("Ran the tests; they all pass", ["Ran the tests; they all pass"]),
        ("Ran 42 tests, all passing", ["Ran 42 tests, all passing"]),
        ("Updated X (and ran the tests)", ["Updated X (and ran the tests)"]),
        (
            "Updated the parser, and the tests now pass",
            ["Updated the parser", "the tests now pass"],
        ),
        ("I ran `a; b` and it works", ["I ran `a; b`", "it works"]),
        ("Fixed it but 2 tests still fail", ["Fixed it", "2 tests still fail"]),
        ("Fixed it, so I could not run mypy", ["Fixed it", "I could not run mypy"]),
        ("Updated the docs and the README", ["Updated the docs and the README"]),
        ("Tests: pass, lint: clean", ["Tests: pass", "lint: clean"]),
        ("Updated a.py and then ran the tests", ["Updated a.py", "ran the tests"]),
        ("; leading", ["leading"]),
    ],
)
def test_split_clauses(text: str, expected: list[str]) -> None:
    assert clauses(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # the counts of one test summary stay together
        ("Tests: 42 passed, 0 failed", ["Tests: 42 passed, 0 failed"]),
        ("pytest: 3 failed, 39 passed, 1 skipped", ["pytest: 3 failed, 39 passed, 1 skipped"]),
        ("12 passed and 1 failed", ["12 passed and 1 failed"]),
        ("Ran 14 tests, 12 passed, 2 failed", ["Ran 14 tests, 12 passed, 2 failed"]),
        ("Fixed it, 2 tests still fail", ["Fixed it", "2 tests still fail"]),
        # an opening phrase that dates the statement keeps it
        ("Before my change, 3 tests failed", ["Before my change, 3 tests failed"]),
        ("Initially, 2 tests failed", ["Initially, 2 tests failed"]),
        (
            "Since Postgres is down, I could not run it",
            ["Since Postgres is down", "I could not run it"],
        ),
        # an opening location keeps the change made there
        ("In `src/app.py`, added a flag", ["In `src/app.py`, added a flag"]),
        # inline code followed by a status verb starts a statement
        (
            "`npm run build` succeeds and `npm test` reports 31 passing",
            ["`npm run build` succeeds", "`npm test` reports 31 passing"],
        ),
        ("`ruff` is clean and `mypy` is green", ["`ruff` is clean", "`mypy` is green"]),
        ("`a.py` and `b.py` were updated", ["`a.py` and `b.py` were updated"]),
        ("Updated it, can't run mypy here", ["Updated it", "can't run mypy here"]),
    ],
)
def test_split_clauses_keeps_or_cuts(text: str, expected: list[str]) -> None:
    assert clauses(text) == expected


def test_split_clauses_offsets_and_degenerate_input() -> None:
    text = "zz Fixed it; tests pass zz"
    assert split_clauses(text, 3, 23) == [(3, 11), (13, 23)]
    assert split_clauses("") == []
    assert split_clauses(";") == []


# --- lists ---------------------------------------------------------------------------


def test_list_markers_checkboxes_and_numbering() -> None:
    report = "- one item\n* two item\n+ three item\n1. four item\n2) five item\n- [ ] six item\n"
    expected = ["one item", "two item", "three item", "four item", "five item", "six item"]
    assert texts(report) == expected
    assert {u.kind for u in segment(report).units} == {"list_item"}


def test_nested_items_take_the_parent_label_as_context() -> None:
    report = "- Files changed:\n  - `a.py`\n  - `b.py`\n- Other\n"
    units = {u.text: u for u in segment(report).units}
    assert units["`a.py`"].context == "Files changed"
    assert units["`b.py`"].context == "Files changed"
    assert units["Other"].context == ""
    report = "## Summary\n- parent\n  - child\n"
    assert {u.text: u.context for u in segment(report).units}["child"] == "Summary"


def test_lead_labels_and_their_reset() -> None:
    report = (
        "Files changed:\n- `a.py`\n\n- `b.py`\n\nSome prose here.\n\n- `c.py`\n\n"
        "**Commands run**\n- `pytest`\n"
    )
    contexts = {u.text: u.context for u in segment(report).units}
    assert contexts["`a.py`"] == "Files changed"
    assert contexts["`b.py`"] == "Files changed"
    assert contexts["`c.py`"] == ""
    assert contexts["`pytest`"] == "Commands run"


def test_lazy_continuation_and_empty_items() -> None:
    report = "- item one\ncontinues here. Second sentence.\n-\n- last"
    assert texts(report) == ["item one\ncontinues here.", "Second sentence.", "last"]


def test_list_after_paragraph_without_blank_line() -> None:
    report = "Here is what changed:\n- Updated `a.py`\n"
    units = segment(report).units
    assert [u.text for u in units] == ["Here is what changed:", "Updated `a.py`"]
    assert units[1].context == "Here is what changed"


# --- tables, headings, quotes ----------------------------------------------------------


def test_tables_with_and_without_header() -> None:
    report = (
        "Files changed:\n\n| File | Change |\n|:---|---:|\n"
        "| `a.py` | Added |\n| b.py | Modified |\n"
    )
    units = segment(report).units
    rows = [u for u in units if u.kind == "table_row"]
    assert [u.text for u in rows] == ["| `a.py` | Added |", "| b.py | Modified |"]
    assert all(u.header == ("file", "change") for u in rows)
    assert all(u.context == "Files changed" for u in rows)
    bare = segment("| pytest | 3 passed |\n| ruff | clean |\n").units
    assert [u.header for u in bare] == [(), ()]
    assert [u.text for u in bare] == ["| pytest | 3 passed |", "| ruff | clean |"]


def test_table_after_a_list_does_not_inherit_the_label() -> None:
    report = "Files changed:\n- a.py\n\n| A | B |\n|---|---|\n| x | y |\n"
    row = next(u for u in segment(report).units if u.kind == "table_row")
    assert row.context == ""


def test_header_row_detected_without_leading_pipe() -> None:
    report = "Check | Result\n---|---\npytest | 3 passed\n\nAfter."
    units = segment(report).units
    assert [u.text for u in units] == ["pytest | 3 passed", "After."]
    assert units[0].header == ("check", "result")


def test_headings_set_the_section() -> None:
    report = "# Summary ##\nDone.\n\n## \n### Tests\n- ok\n"
    units = segment(report).units
    assert [(u.text, u.kind, u.context) for u in units] == [
        ("Summary", "heading", ""),
        ("Done.", "sentence", "Summary"),
        ("Tests", "heading", ""),
        ("ok", "list_item", "Tests"),
    ]


def test_block_quotes_are_paragraphs() -> None:
    report = "> All tests pass.\n> Lint is clean.\n"
    assert texts(report) == ["All tests pass.", "Lint is clean."]


# --- helpers -------------------------------------------------------------------------


def test_code_spans() -> None:
    assert code_spans("a `b` c ``d ` e`` f") == [(2, 5), (8, 17)]
    assert code_spans("unclosed ` here") == []
    assert code_spans("`a`` b `c`") == [(0, 8)]
    assert code_spans("") == []


def test_mask_markdown_keeps_length_and_offsets() -> None:
    text = "**Fixed** the [docs](README.md) <br> _now_ \u2014 it\u2019s `x*y` ok"
    masked = mask_markdown(text)
    assert len(masked) == len(text)
    assert masked == "  Fixed   the  docs  README.md        now  - it's `x*y` ok"
    assert mask_markdown(text, blank_code=True).endswith("`CCC` ok")
    assert mask_markdown("src/pkg/__init__.py and __main__") == "src/pkg/__init__.py and __main__"
    assert mask_markdown("`[a](b)` and `<br>`") == "`[a](b)` and `<br>`"


def test_clean_label() -> None:
    assert clean_label("**Files changed:**") == "Files changed"
    assert clean_label("## `src/` changes") == "src/ changes"
    assert clean_label("  ") == ""


def test_table_cells() -> None:
    row = "| `a|b` | x \\| y |  z  |"
    assert [row[a:b] for a, b in table_cells(row)] == ["`a|b`", "x \\| y", "z"]
    row = "a | b"
    assert [row[a:b] for a, b in table_cells(row)] == ["a", "b"]
    row = "| | x |"
    assert [row[a:b] for a, b in table_cells(row)] == ["", "x"]


def test_unit_defaults() -> None:
    unit = Unit("x", (0, 1), "sentence")
    assert unit.context == "" and unit.first and unit.header == () and unit.previous == ""
