from datetime import date
from itertools import islice

import pytest
from dateseq.ranges import date_range, day_count, weekday_count, weekdays


def test_range_starts_at_the_start_date() -> None:
    assert next(date_range(date(2026, 3, 2), date(2026, 3, 9))) == date(2026, 3, 2)


def test_range_steps_one_day_at_a_time() -> None:
    first = list(islice(date_range(date(2026, 3, 2), date(2026, 3, 31)), 3))
    assert first == [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]


def test_range_crosses_the_end_of_a_month() -> None:
    first = list(islice(date_range(date(2026, 2, 27), date(2026, 3, 31)), 3))
    assert first == [date(2026, 2, 27), date(2026, 2, 28), date(2026, 3, 1)]


def test_range_crosses_a_leap_day() -> None:
    first = list(islice(date_range(date(2028, 2, 28), date(2028, 3, 31)), 2))
    assert first == [date(2028, 2, 28), date(2028, 2, 29)]


def test_range_crosses_the_end_of_a_year() -> None:
    first = list(islice(date_range(date(2026, 12, 30), date(2027, 1, 31)), 3))
    assert first == [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1)]


def test_range_is_empty_when_the_end_is_before_the_start() -> None:
    assert list(date_range(date(2026, 3, 9), date(2026, 3, 2))) == []


def test_range_is_produced_lazily() -> None:
    dates = date_range(date(2026, 1, 1), date(9999, 12, 31))
    assert list(islice(dates, 2)) == [date(2026, 1, 1), date(2026, 1, 2)]


def test_weekdays_skip_saturday_and_sunday() -> None:
    friday, saturday, sunday, monday = (date(2026, 3, day) for day in (6, 7, 8, 9))
    assert list(weekdays([friday, saturday, sunday, monday])) == [friday, monday]


def test_day_count_includes_both_ends() -> None:
    assert day_count(date(2026, 3, 1), date(2026, 3, 31)) == 31
    assert day_count(date(2026, 3, 5), date(2026, 3, 5)) == 1


def test_day_count_is_zero_when_the_end_is_before_the_start() -> None:
    assert day_count(date(2026, 3, 9), date(2026, 3, 2)) == 0


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 3, 2), date(2026, 3, 15), 10),
        (date(2026, 3, 7), date(2026, 3, 8), 0),
        (date(2026, 3, 6), date(2026, 3, 9), 2),
        (date(2026, 3, 1), date(2026, 3, 31), 22),
        (date(2026, 3, 9), date(2026, 3, 2), 0),
    ],
)
def test_weekday_count(start: date, end: date, expected: int) -> None:
    assert weekday_count(start, end) == expected
