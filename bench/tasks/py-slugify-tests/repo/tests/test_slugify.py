import pytest
from textkit import slugify


def test_words_are_joined_with_a_hyphen():
    assert slugify("hello big world") == "hello-big-world"


def test_the_slug_is_lowercase():
    assert slugify("Hello World") == "hello-world"


def test_surrounding_whitespace_is_ignored():
    assert slugify("   padded title \n") == "padded-title"


def test_tabs_and_newlines_separate_words():
    assert slugify("one\ttwo\nthree") == "one-two-three"


def test_punctuation_between_words_is_one_separator():
    assert slugify("first, second; third") == "first-second-third"


def test_an_empty_title_gives_an_empty_slug():
    assert slugify("") == ""


def test_a_title_without_letters_gives_an_empty_slug():
    assert slugify("?!...") == ""


def test_a_short_title_is_not_changed_by_a_large_max_length():
    assert slugify("short title", max_length=50) == "short-title"


def test_a_value_that_is_not_text_is_rejected():
    with pytest.raises(TypeError):
        slugify(42)  # type: ignore[arg-type]


def test_an_unknown_separator_is_rejected():
    with pytest.raises(ValueError, match="separator"):
        slugify("a b", separator="~")


def test_a_max_length_below_one_is_rejected():
    with pytest.raises(ValueError, match="max_length"):
        slugify("a b", max_length=0)
