from datetime import date

import pytest
from bizdays.arith import add_business_days, is_business_day

CLOSURES = frozenset({date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 28)})


def test_weekdays_are_business_days() -> None:
    assert is_business_day(date(2026, 3, 2))
    assert is_business_day(date(2026, 3, 6))


def test_weekends_are_not_business_days() -> None:
    assert not is_business_day(date(2026, 3, 7))
    assert not is_business_day(date(2026, 3, 8))


def test_closure_days_are_not_business_days() -> None:
    assert not is_business_day(date(2026, 12, 24), CLOSURES)


def test_add_one_from_friday_is_monday() -> None:
    assert add_business_days(date(2026, 3, 6), 1) == date(2026, 3, 9)


def test_add_zero_returns_the_start() -> None:
    assert add_business_days(date(2026, 3, 7), 0) == date(2026, 3, 7)


def test_add_skips_weekends_across_weeks() -> None:
    assert add_business_days(date(2026, 3, 2), 10) == date(2026, 3, 16)


def test_add_skips_closure_days() -> None:
    assert add_business_days(date(2026, 12, 23), 1, CLOSURES) == date(2026, 12, 29)


def test_add_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        add_business_days(date(2026, 3, 2), -1)
