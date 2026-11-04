from decimal import Decimal

from csvsummary.render import render_summary, render_top
from csvsummary.stats import ColumnStats

COLUMNS = [
    ColumnStats("order", 3, 3),
    ColumnStats("total", 3, 2, "8", "30.25", Decimal("16.5")),
]


def test_summary_starts_with_the_counts() -> None:
    assert render_summary(3, COLUMNS).splitlines()[:3] == ["rows: 3", "columns: 2", ""]


def test_summary_lines_are_aligned() -> None:
    assert render_summary(3, COLUMNS).splitlines()[3:] == [
        "column  filled  distinct  min         max         mean",
        "order        3         3",
        "total        3         2  8           30.25       16.50",
    ]


def test_long_column_names_widen_the_first_column() -> None:
    lines = render_summary(1, [ColumnStats("customer_name", 1, 1)]).splitlines()
    assert lines[3].startswith("column         filled")
    assert lines[4] == "customer_name       1         1"


def test_top_lists_counts_and_values() -> None:
    assert render_top([("Porto", 3), ("Lisbon", 12)]) == "     3  Porto\n    12  Lisbon\n"


def test_top_shows_empty_values() -> None:
    assert render_top([("", 2)]) == "     2  (empty)\n"


def test_top_without_values_prints_nothing() -> None:
    assert render_top([]) == ""
