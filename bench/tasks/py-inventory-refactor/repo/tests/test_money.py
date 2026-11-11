import pytest
from stockroom.money import format_cents, percent_of


@pytest.mark.parametrize(
    ("cents", "pct", "expected"),
    [(1000, 10, 100), (1005, 10, 101), (1004, 10, 100), (0, 5, 0), (199, 3, 6)],
)
def test_percent_of_rounds_half_up(cents: int, pct: int, expected: int) -> None:
    assert percent_of(cents, pct) == expected


@pytest.mark.parametrize(
    ("cents", "text"), [(0, "0.00"), (5, "0.05"), (1290, "12.90"), (-250, "-2.50")]
)
def test_format_cents(cents: int, text: str) -> None:
    assert format_cents(cents) == text
