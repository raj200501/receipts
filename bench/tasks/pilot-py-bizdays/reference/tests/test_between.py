from datetime import date

import pytest
from bizdays.arith import add_business_days, business_days_between

CLOSURES = frozenset({date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 28)})


def test_friday_to_monday_is_one_business_day() -> None:
    assert business_days_between(date(2026, 3, 6), date(2026, 3, 9)) == 1


def test_same_day_is_zero() -> None:
    assert business_days_between(date(2026, 3, 7), date(2026, 3, 7)) == 0


def test_closure_days_are_not_counted() -> None:
    assert business_days_between(date(2026, 12, 23), date(2026, 12, 29), CLOSURES) == 1


@pytest.mark.parametrize("count", [0, 1, 4, 10, 25])
def test_between_is_the_inverse_of_add(count: int) -> None:
    start = date(2026, 12, 21)
    end = add_business_days(start, count, CLOSURES)
    assert business_days_between(start, end, CLOSURES) == count


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="before"):
        business_days_between(date(2026, 3, 9), date(2026, 3, 6))
