"""Rules 7 and 8 of docs/SLUG_RULES.md: stopwords and unique slugs."""

import pytest
from textkit import slugify, unique_slug


def test_stopwords_are_left_out():
    assert slugify("The Rust Book", stopwords=["the"]) == "rust-book"
    assert slugify("a tale of two cities", stopwords=["a", "of"]) == "tale-two-cities"


def test_stopwords_match_whatever_the_case():
    assert slugify("The Rust Book", stopwords=["The"]) == "rust-book"
    assert slugify("the rust book", stopwords=["THE"]) == "rust-book"


def test_stopwords_match_whole_words_only():
    assert slugify("Theory of the Thing", stopwords=["the"]) == "theory-of-thing"


def test_a_title_of_stopwords_only_keeps_its_words():
    assert slugify("The", stopwords=["the"]) == "the"
    assert slugify("To Be Or Not", stopwords=["to", "be", "or", "not"]) == "to-be-or-not"


def test_unique_slug_returns_a_free_slug_unchanged():
    assert unique_slug("Intro", {"overview"}) == "intro"


def test_unique_slug_numbers_from_two():
    assert unique_slug("Intro", {"intro"}) == "intro-2"
    assert unique_slug("Intro", {"intro", "intro-2"}) == "intro-3"
    assert unique_slug("Intro", {"intro", "intro-3"}) == "intro-2"


def test_unique_slug_uses_the_chosen_separator():
    assert unique_slug("Getting Started", {"getting_started"}, separator="_") == "getting_started_2"


def test_the_number_counts_toward_max_length():
    taken = {"getting-started"}
    assert unique_slug("Getting Started", taken, max_length=15) == "getting-start-2"
    assert unique_slug("Getting Started", {"getting"}, max_length=7) == "getti-2"


@pytest.mark.parametrize("title", ["", "???", "日本"])
def test_a_title_without_letters_or_digits_is_untitled(title):
    assert unique_slug(title, set()) == "untitled"
    assert unique_slug(title, {"untitled"}) == "untitled-2"
