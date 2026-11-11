"""Rule 1 of docs/SLUG_RULES.md: accents are folded."""

import pytest
from textkit import fold, slugify


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Café", "cafe"),
        ("Crème brûlée", "creme-brulee"),
        ("Zürich über alles", "zurich-uber-alles"),
        ("El Niño", "el-nino"),
        ("Å Ç Ê", "a-c-e"),
    ],
)
def test_accented_letters_become_plain_letters(title, expected):
    assert slugify(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Straße", "strasse"),
        ("Æther", "aether"),
        ("æther", "aether"),
        ("Cœur", "coeur"),
        ("Ørsted", "orsted"),
        ("Smørrebrød", "smorrebrod"),
        ("Đorđe", "dorde"),
        ("Łódź", "lodz"),
        ("Þór", "thor"),
        ("Ðe", "de"),
    ],
)
def test_special_letters_are_spelled_out_capitals_included(title, expected):
    assert slugify(title) == expected


def test_letters_outside_the_latin_alphabet_are_dropped():
    assert slugify("Привет world 你好") == "world"
    assert slugify("日本語") == ""


def test_fold_keeps_the_case_and_the_punctuation():
    assert fold("Ça va, Éric!") == "Ca va, Eric!"
    assert fold("Straße") == "Strasse"
