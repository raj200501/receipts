from decimal import Decimal

import pytest
from csvsummary.reader import parse_table
from csvsummary.stats import as_number, column_stats, summarize, top_values


@pytest.mark.parametrize("text", ["12", "-3", "+4.5", "0.25", " 7 "])
def test_plain_decimals_are_numbers(text: str) -> None:
    assert as_number(text) == Decimal(text.strip())


@pytest.mark.parametrize("text", ["1,250", "1e3", "4.", ".5", "n/a", ""])
def test_other_values_are_not_numbers(text: str) -> None:
    assert as_number(text) is None


def test_filled_ignores_empty_and_blank_values() -> None:
    assert column_stats("note", ["a", "", "  ", "b"]).filled == 2


def test_distinct_compares_values_without_surrounding_spaces() -> None:
    assert column_stats("city", ["Porto", " Porto", "Lisbon", ""]).distinct == 2


def test_numeric_column_has_min_max_and_mean() -> None:
    stats = column_stats("total", ["12.50", "8", "", "30.50"])
    assert (stats.minimum, stats.maximum) == ("8", "30.50")
    assert stats.mean == Decimal("17")
    assert stats.numeric


def test_one_text_value_makes_the_column_non_numeric() -> None:
    stats = column_stats("total", ["12.50", "n/a", "8"])
    assert (stats.minimum, stats.maximum, stats.mean) == ("", "", None)
    assert not stats.numeric


def test_empty_column_is_not_numeric() -> None:
    assert not column_stats("note", ["", ""]).numeric


def test_summarize_keeps_the_header_order() -> None:
    table = parse_table("b,a\n1,x\n2,y\n")
    assert [stats.name for stats in summarize(table)] == ["b", "a"]


def test_top_values_orders_by_count_then_value() -> None:
    values = ["Porto", "Lisbon", "Braga", "Porto", "Lisbon", "Porto", "Aveiro"]
    assert top_values(values) == [("Porto", 3), ("Lisbon", 2), ("Aveiro", 1), ("Braga", 1)]


def test_top_values_counts_empty_values() -> None:
    assert top_values(["", "x", " "]) == [("", 2), ("x", 1)]


def test_top_values_respects_the_limit() -> None:
    assert top_values(["a", "b", "b", "c"], limit=2) == [("b", 2), ("a", 1)]
