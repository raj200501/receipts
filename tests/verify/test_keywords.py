"""Tests for receipts.verify.keywords (inputs are synthetic phrases)."""

from __future__ import annotations

import pytest

from receipts.verify.keywords import STOPWORDS, keywords, map_requirements, overlap, stem


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("boundaries", "boundary"),
        ("boundary", "boundary"),
        ("parsing", "pars"),
        ("parse", "pars"),
        ("parser", "pars"),
        ("parsed", "pars"),
        ("dates", "dat"),
        ("date", "dat"),
        ("fixes", "fix"),
        ("fix", "fix"),
        ("Months", "month"),
        ("ui", "ui"),
    ],
)
def test_stem(word: str, expected: str) -> None:
    assert stem(word) == expected


def test_keywords_split_snake_and_camel_case_and_drop_stopwords() -> None:
    words = keywords("Fixed the bug in parse_date and parseMonth for the tests")
    assert words == {"pars", "dat", "month"}


def test_keywords_drop_one_letter_words_and_keep_numbers() -> None:
    assert keywords("a b 404 x") == {"404"}


def test_stopwords_are_lowercase() -> None:
    assert all(w == w.lower() for w in STOPWORDS)


def test_overlap_counts_shared_keywords() -> None:
    assert overlap("could not install psycopg2", "pip install psycopg2-binary") == 2
    assert overlap("the docs", "pytest -q") == 0


REQS = {
    "R1": "parse_date handles month boundaries",
    "R2": "Add a --json flag to the CLI output",
    "R3": "Month names are localized",
}


def test_map_requirements_by_explicit_id() -> None:
    assert map_requirements("R2 is done, and r3 too", REQS) == ("R2", "R3")


def test_map_requirements_id_must_be_a_whole_word() -> None:
    assert map_requirements("see R22 and XR2", {"R2": "unrelated words"}) == ()


def test_map_requirements_by_best_overlap() -> None:
    assert map_requirements("fixed the month boundary bug in parse_date", REQS) == ("R1",)
    assert map_requirements("added json output", REQS) == ("R2",)


def test_map_requirements_keeps_ties() -> None:
    assert map_requirements("months", REQS) == ("R1", "R3")


def test_map_requirements_no_overlap() -> None:
    assert map_requirements("updated the README", REQS) == ()
    assert map_requirements("anything", {}) == ()
